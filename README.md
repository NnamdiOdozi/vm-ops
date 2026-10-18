# vm-ops

Machine-level checks for the Hetzner VM (`ubuntu-4gb-nbg1-2`). It holds things that belong to
the **machine** rather than to any one app: today, a disk alert.

## Why this exists

On 2026-10-18 the VM's only disk reached 99% without anyone noticing. Nothing warned
beforehand; the first symptom was VS Code failing to connect with "No space left on device".
A full disk breaks every app on the VM at once: logs stop being written, Let's Encrypt
cannot renew certificates, and databases can corrupt. The space turned out to be old caches,
a 6 GB backup and 1.4 GB of system logs, all of which had been growing silently for months.

The check lives in its own repository, not in `fixed_income`, because the disk is shared.
If any one app were moved or removed, monitoring for all the others must not go with it.

## What it does

Every 15 minutes a systemd timer (Linux's built-in scheduler) runs one short Python check.
It reads how full the disk is and keeps the last six hours of readings, so the fill rate is
an average over hours rather than one 15-minute jump. It emails only when one of two rules
breaks:

| Rule | Triggers when | Default |
|---|---|---|
| **nearly full** | used space reaches a percentage, counted the way `df` counts it | 85% |
| **filling fast** | free space fell by at least 5 GB within the last 6 hours, and at that average rate the disk would be full within 24 hours | 6-hour window, 5 GB minimum, 24-hour horizon |

Each rule emails at most once every 6 hours, so a disk sitting at 86% does not send an email
every 15 minutes.

**Which folders grew.** Once a day, on the first run after 03:00 UTC, the check records the
size of every folder three levels deep (for example `/root/.cache/uv`) using `du`. When an
alert fires, it measures again and the email lists the ten folders that grew most since that
baseline, and the ten largest overall. Each byte is counted once, against the deepest folder
holding it, so one culprit does not also appear as its parents `/root` and `/`. A parent's
own files are shown as `/root (files directly inside)`.

**Space in no folder.** If the disk reports more than 1 GB used that `du` cannot find, the
email says so. That almost always means a process still holds a file that was deleted; the
space only returns when the process restarts, and `sudo lsof +L1` lists the culprits.

All thresholds are in `config.toml`. Nothing is hardcoded in the code.

## Where things live on the VM

| Path | What it holds |
|---|---|
| `/opt/vm-ops` | this repository, cloned. `/opt` is the conventional place for add-on software |
| `/etc/vm-ops/config.toml` | the settings, copied from the repo on first install only, so local edits survive updates |
| `/etc/vm-ops/smtp.env` | the Gmail sender and app password, readable by root only; never in git |
| `/var/lib/vm-ops/disk_state.json` | the last reading, when each rule last emailed, and the daily folder baseline |
| systemd journal | the logs: `journalctl -u vm-disk-alert` |

It runs with the system's own `python3` (3.11 or later) and the standard library only, so
there is no virtual environment on the VM and nothing to `pip install`.

## Install (once)

All steps are on the VM, logged in as `nnamdi`.

**1. Give the VM read access to this repository.** GitHub allows one deploy key per
repository, so `fixed_income`'s key cannot be reused:

```bash
ssh-keygen -t ed25519 -C "hetzner vm-ops deploy" -f ~/.ssh/vm_ops_deploy -N ""
cat ~/.ssh/vm_ops_deploy.pub     # paste into GitHub: vm-ops > Settings > Deploy keys (read-only)
cat >> ~/.ssh/config <<'EOF'

Host github-vm-ops
    HostName github.com
    IdentityFile ~/.ssh/vm_ops_deploy
    IdentitiesOnly yes
EOF
ssh -T git@github-vm-ops         # expect "Hi NnamdiOdozi/vm-ops! You've successfully authenticated"
```

**2. Clone and install.** The clone is owned by you, because root has no GitHub key:

```bash
sudo install -d -o nnamdi -g nnamdi /opt/vm-ops
git clone git@github-vm-ops:NnamdiOdozi/vm-ops.git /opt/vm-ops
cd /opt/vm-ops && sudo bash install.sh
```

The first run stops before enabling the timer, because there are no mail credentials yet.

**3. Add the Gmail app password.** Create a new app password in your Google account
(Security > App passwords) named "vm-ops". A separate password means revoking one never
breaks the curve API's alerts. Then:

```bash
sudo nano /etc/vm-ops/smtp.env
#   SMTP_USER=your.address@gmail.com
#   SMTP_PASSWORD=the sixteen-letter app password
sudo bash install.sh             # now enables the timer
```

**4. Check it works.**

```bash
sudo bash -c 'set -a; . /etc/vm-ops/smtp.env; set +a; PYTHONPATH=/opt/vm-ops/src python3 -m vm_ops.disk_alert --test-email'
sudo env PYTHONPATH=/opt/vm-ops/src python3 -m vm_ops.disk_alert --dry-run
systemctl list-timers vm-disk-alert.timer
```

The first sends one test email. The second prints what an alert would say right now,
without sending or saving anything. The third shows when the timer next runs.

## Update

```bash
cd /opt/vm-ops && git pull && sudo bash install.sh
```

`install.sh` never overwrites `/etc/vm-ops/config.toml`, so a setting added to the repo is
missing on the VM until you copy it across; the code would then stop with a KeyError in the
journal. The installer prints the difference between the two files to make that visible.

## Develop and test (laptop)

```bash
uv sync
uv run pytest -q
```

The tests replace the disk, `du` and Gmail with stand-ins, so they run anywhere in a
fraction of a second and send nothing. `disk_check.py` holds every rule as a pure function;
`disk_alert.py` does all the reading, writing and sending.

## Limitations

- If the VM itself is down, nothing is sent. UptimeRobot's check of the curve API covers that.
- Ordinary bursts (a VS Code login, a 3 GB library install) stay under the 5 GB minimum and
  send nothing. A single burst of more than 5 GB, even one deleted soon after, sends one
  "filling fast" email. Slow growth is caught by the 85% rule instead.
- Growth is reported by folder, not by file, and only three levels deep. You then drill in
  by hand with `sudo du -xh --max-depth=1 <folder> | sort -h`.
- The first alert after install has no baseline yet, so it lists only the largest folders.
