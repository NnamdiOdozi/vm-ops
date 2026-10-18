# Design choices

## A separate repository, not part of fixed_income (2026-10-18)

The disk is shared by every app on the VM. Monitoring it from one app's repository would
make that app's deploy script own machine-wide monitoring, and removing the app would
silently remove the alerts for everything else.

## Percent used follows df, not raw used/total

`shutil.disk_usage` reports `free` as the space an ordinary user can still write, which
excludes ext4's ~5% root reserve. Percent is `used / (used + free)`, the same as `df`, so
the alert agrees with what a person sees when they run `df -h`. Raw `used / total` read 95%
on the day `df` showed 99%.

## Growth is attributed to each folder's own bytes

`du` totals nest: `/root` includes `/root/.cache`, which includes `/root/.cache/uv`. Ranking
the totals directly fills the top ten with the ancestors of one culprit. `own_sizes`
subtracts each folder's direct children, so every byte is counted once, against the
deepest folder in the snapshot that holds it. A parent keeps only files directly inside it
(and anything deeper than `du_depth`), and is labelled "(files directly inside)".

## The comparison baseline is the snapshot before this run

If the daily snapshot is due on the same run that sends an alert, the email still compares
against the previous day's snapshot, captured before it is replaced. Comparing against the
snapshot just taken would always show zero growth.

## A rule that has never emailed is always due

The cooldown first used `last_alerts.get(rule, 0)`, which treated "never sent" as "sent at
time 0". That only works because real clock times are huge; with small timestamps it
suppressed a first alert. The rule is now explicit: absent from `last_alerts` means due.

## The hidden-space hint only applies at a mount point

The "space in no folder" check compares df's figure for the whole filesystem with du's
total for the checked path. Below a mount point those measure different things, and a
dry run on a laptop subfolder wrongly reported 171 GB hidden. The hint is now skipped
unless the path is a mount point (`os.path.ismount`).

## Its own Gmail app password

`/etc/vm-ops/smtp.env` holds a separate app password from the curve API's
`/etc/fixed-income-api/smtp.env`. Revoking either never breaks the other, and vm-ops does
not depend on a file another project's deploy owns.
