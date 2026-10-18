"""Disk alert for the whole VM: run every 15 minutes by vm-disk-alert.timer.

Emails when the disk is nearly full or filling fast, with the folders that grew most since
the daily baseline snapshot. SMTP_USER and SMTP_PASSWORD (a Gmail app password) come from
the environment, which systemd loads from the root-only /etc/vm-ops/smtp.env.

    python3 -m vm_ops.disk_alert --config /etc/vm-ops/config.toml [--dry-run | --test-email]
"""

import argparse
import json
import os
import shutil
import smtplib
import socket
import subprocess
import time
import tomllib
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from vm_ops import disk_check
from vm_ops.disk_check import GB

RUN_ID = uuid.uuid4().hex[:8]


def log(event, **fields):
    # One key=value line per event; journald stores it, `journalctl -u vm-disk-alert` reads it.
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    extras = " ".join(f"{k}={json.dumps(v) if isinstance(v, str) else v}" for k, v in fields.items())
    print(f"{stamp} run_id={RUN_ID} event={event} {extras}", flush=True)


def read_disk(path, now):
    usage = shutil.disk_usage(path)
    return {"time": now, "used": usage.used, "free": usage.free}


def run_du(root, depth, timeout):
    started = time.monotonic()
    # -x: stay on this filesystem; -B1: exact bytes. Exit status 1 just means some path was
    # unreadable or vanished mid-scan, so the output is still used.
    result = subprocess.run(["du", "-x", "-B1", f"--max-depth={depth}", root],
                            capture_output=True, text=True, timeout=timeout)
    sizes = disk_check.parse_du(result.stdout)
    log("du_snapshot", root=root, depth=depth, folders=len(sizes), exit_code=result.returncode,
        elapsed_s=round(time.monotonic() - started, 1))
    return sizes


def snapshot_due(snapshot, now, hour_utc):
    if not snapshot:
        return True
    today = datetime.fromtimestamp(now, timezone.utc)
    taken = datetime.fromtimestamp(snapshot["time"], timezone.utc)
    return today.hour >= hour_utc and taken.date() < today.date()


def gb_rows(rows, signed=False):
    fmt = "{:+8.2f} GB  {}" if signed else "{:8.2f} GB  {}"
    return "\n".join(fmt.format(b / GB, name) for b, name in rows) or "  (none)"


def compose(problems, reading, sizes, snapshot, cfg):
    g = cfg["growth"]
    parts = [msg for _, msg in problems]
    if snapshot:
        taken = datetime.fromtimestamp(snapshot["time"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts.append(f"Grew most since the baseline of {taken}:\n"
                     + gb_rows(disk_check.growth_rows(snapshot["sizes"], sizes, g["top_n"],
                                               g["min_growth_gb"] * GB), signed=True))
    else:
        parts.append("No baseline snapshot yet, so growth cannot be attributed this time.")
    parts.append("Largest folders now:\n" + gb_rows(disk_check.largest_rows(sizes, g["top_n"])))
    root = cfg["disk"]["path"]
    # df counts the whole filesystem, so the comparison only means something at its mount point.
    hidden = disk_check.unaccounted_bytes(reading, sizes, root) if os.path.ismount(root) else 0
    if hidden > g["unaccounted_gb"] * GB:
        parts.append(f"{hidden / GB:.1f} GB is in use but in no folder. A process is probably "
                     "holding files that were deleted; `sudo lsof +L1` lists them, and the space "
                     "returns when that process restarts.")
    return "\n\n".join(parts)


def send(subject, body, cfg):
    e = cfg["email"]
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = subject, os.environ["SMTP_USER"], e["alert_to"]
    message.set_content(body)
    with smtplib.SMTP(e["smtp_host"], e["smtp_port"], timeout=30) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


def load_state(path):
    return json.loads(path.read_text()) if path.exists() else {"last_alerts": {}}


def run(cfg, now, dry_run=False, disk=read_disk, du=run_du, mail=send):
    d, g = cfg["disk"], cfg["growth"]
    state_path = Path(cfg["paths"]["state_file"])
    state = load_state(state_path)
    reading = disk(d["path"], now)
    history = state.get("history", [])
    problems = disk_check.disk_problems(reading, history, d)
    to_send = disk_check.due(problems, state["last_alerts"], now, d["cooldown_hours"])
    log("check", percent_used=round(disk_check.percent_used(reading), 1),
        free_gb=round(reading["free"] / GB, 2), problems=len(problems), due=len(to_send))

    sizes = None
    # Compare against the baseline as it stood before this run, even if it is replaced now.
    baseline = state.get("snapshot")
    if snapshot_due(baseline, now, g["snapshot_hour_utc"]):
        sizes = du(d["path"], g["du_depth"], g["du_timeout_seconds"])
        state["snapshot"] = {"time": now, "sizes": sizes}
        log("baseline_saved", folders=len(sizes), dry_run=dry_run)

    if to_send:
        sizes = sizes or du(d["path"], g["du_depth"], g["du_timeout_seconds"])
        subject = (f"{cfg['email']['subject_prefix']} {socket.gethostname()}: "
                   + ", ".join(rule.replace("_", " ") for rule, _ in to_send))
        body = compose(to_send, reading, sizes, baseline, cfg)
        if dry_run:
            print(f"--- would email: {subject}\n{body}")
        else:
            mail(subject, body, cfg)
            for rule, _ in to_send:
                log("alert_sent", rule=rule, to=cfg["email"]["alert_to"],
                    last_sent_before=state["last_alerts"].get(rule))
                state["last_alerts"][rule] = now

    # Keep just the readings the fill-rate window needs (24 per 6 h at 15-minute runs).
    keep_from = now - d["fill_window_hours"] * 3600
    state["history"] = [r for r in history if r["time"] >= keep_from] + [reading]
    state.pop("last_reading", None)  # replaced by history (2026-10-18)
    if not dry_run:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state))
    return to_send


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="/etc/vm-ops/config.toml")
    parser.add_argument("--dry-run", action="store_true", help="print the email; save no state")
    parser.add_argument("--test-email", action="store_true", help="send one test email and exit")
    args = parser.parse_args()
    cfg = tomllib.loads(Path(args.config).read_text())
    if args.test_email:
        send(f"{cfg['email']['subject_prefix']} {socket.gethostname()}: test email",
             "vm-ops can send email from this machine.", cfg)
        log("test_email_sent", to=cfg["email"]["alert_to"])
        return
    run(cfg, time.time(), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
