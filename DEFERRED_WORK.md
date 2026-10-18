# Deferred work

Only items that are still open.

## Move the ML RWP suite off root (2026-10-18)

**Source:** disk clean-up session. The four `mlrwp-diag` processes (Streamlit, its metrics
exporter, TensorBoard) and five systemd units run as root from `/root/mlrwp-diag`. A bug
that let a visitor run code would control the whole VM, including the curve API's keys.
**Scoped:** a no-login service account (as `curveapi` is for the curve API), the app moved
out of `/root`, units updated with `User=`. **Status:** not started.

## Agree monitoring with the VM's other administrator (2026-10-18)

**Source:** disk clean-up session. Docker, MySQL and Postgres on this VM are managed by
someone else, who may already monitor disk or want these alerts. **Status:** not raised.

## Cap the systemd journal permanently (2026-10-18)

**Source:** disk clean-up session. `journalctl --vacuum-size=200M` freed 1.2 GB but does not
stop regrowth. **Scoped:** `SystemMaxUse=200M` in `/etc/systemd/journald.conf`, then restart
`systemd-journald`. Could become a second check or a step in `install.sh`. **Status:** open.
