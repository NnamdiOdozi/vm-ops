"""Pure disk-alert rules: no file, network or subprocess access, so every rule is testable.

A reading is {"time": epoch seconds, "used": bytes, "free": bytes}. "free" is the space an
ordinary user can still write (the root-reserved blocks are excluded), matching df.
"""

import os

GB = 1024 ** 3


def percent_used(reading):
    # df's convention: used / (used + available). The ~5% root reserve is in neither, which
    # is why df shows 99% on a disk whose raw used/total is ~95%.
    return 100 * reading["used"] / (reading["used"] + reading["free"])


def disk_problems(reading, previous, cfg):
    """Return [(rule, message)] for every rule the reading breaks, ignoring cooldowns."""
    problems = []
    pct = percent_used(reading)
    free_gb = reading["free"] / GB
    if pct >= cfg["alert_percent"]:
        problems.append(("nearly_full", f"Disk is {pct:.1f}% used (alert at "
                         f"{cfg['alert_percent']}%); {free_gb:.1f} GB still writable."))
    if previous:
        hours = (reading["time"] - previous["time"]) / 3600
        rate = (previous["free"] - reading["free"]) / GB / hours if hours > 0 else 0
        if rate >= cfg["min_fill_rate_gb_per_hour"]:
            hours_to_full = free_gb / rate
            if hours_to_full <= cfg["fill_alert_hours"]:
                problems.append(("filling_fast", f"Free space fell at {rate:.2f} GB/hour over the "
                                 f"last {hours * 60:.0f} minutes; at that rate the disk is full in "
                                 f"about {hours_to_full:.1f} hours ({free_gb:.1f} GB left)."))
    return problems


def due(problems, last_alerts, now, cooldown_hours):
    """Drop problems whose rule already emailed within the cooldown."""
    return [p for p in problems
            if p[0] not in last_alerts or now - last_alerts[p[0]] >= cooldown_hours * 3600]


def parse_du(text):
    """`du -x -B1 --max-depth=N` output ("bytes<TAB>path" per line) -> {path: bytes}."""
    sizes = {}
    for line in text.splitlines():
        size, _, path = line.partition("\t")
        if path:
            sizes[path] = int(size)
    return sizes


def own_sizes(sizes):
    """Bytes held by each folder itself, excluding its listed subfolders.

    du's totals nest (/root includes /root/.cache), so ranking them directly would fill the
    list with ancestors of one culprit. Subtracting the direct children counts each byte once;
    a deepest folder keeps its whole total, a parent keeps only files sitting directly in it
    (or in subfolders deeper than the snapshot depth).
    """
    own = dict(sizes)
    for path, size in sizes.items():
        parent = os.path.dirname(path)
        if parent != path and parent in own:
            own[parent] -= size
    return own


def label(path, sizes):
    has_children = any(os.path.dirname(p) == path and p != path for p in sizes)
    return f"{path} (files directly inside)" if has_children else path


def growth_rows(before, after, top_n):
    """Top folders by growth of their own size since the baseline: [(bytes grown, label)]."""
    old, new = own_sizes(before), own_sizes(after)
    grown = sorted(((new[p] - old.get(p, 0), p) for p in new), reverse=True)
    return [(g, label(p, after)) for g, p in grown[:top_n] if g > 0]


def largest_rows(sizes, top_n):
    own = own_sizes(sizes)
    return [(s, label(p, sizes)) for s, p in sorted(((s, p) for p, s in own.items()), reverse=True)[:top_n]]


def unaccounted_bytes(reading, sizes, root):
    """Used space du could not find: usually files deleted while a process still holds them."""
    return reading["used"] - sizes.get(root, 0)
