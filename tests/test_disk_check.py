"""The pure rules: thresholds, fill rate, cooldown and growth attribution."""

from vm_ops import disk_check
from vm_ops.disk_check import GB

CFG = {"alert_percent": 85, "fill_alert_hours": 24, "min_fill_rate_gb_per_hour": 0.5}


def reading(used_gb, free_gb, time=0):
    return {"time": time, "used": used_gb * GB, "free": free_gb * GB}


def rules(problems):
    return [rule for rule, _ in problems]


def test_percent_uses_df_convention():
    # 36 GB used, 0.5 GB writable: df says 99%, not 36/38.
    assert round(disk_check.percent_used(reading(36, 0.5)), 1) == 98.6


def test_nearly_full_triggers_at_threshold_only():
    assert rules(disk_check.disk_problems(reading(85, 15), None, CFG)) == ["nearly_full"]
    assert disk_check.disk_problems(reading(84, 16), None, CFG) == []


def test_filling_fast_when_full_within_window():
    # 2 GB lost in 15 minutes = 8 GB/h; 20 GB left -> full in 2.5 h, though only 60% used.
    before, now = reading(28, 22, 0), reading(30, 20, 900)
    assert rules(disk_check.disk_problems(now, before, CFG)) == ["filling_fast"]


def test_slow_growth_is_not_an_alert():
    # 0.1 GB in 15 minutes = 0.4 GB/h, below the noise floor even though 20 GB would last 50 h.
    assert disk_check.disk_problems(reading(30, 20, 900), reading(29.9, 20.1, 0), CFG) == []


def test_fast_but_distant_full_is_not_an_alert():
    # 1 GB/h with 30 GB left is 30 h away: outside the 24 h window.
    assert disk_check.disk_problems(reading(20, 30, 3600), reading(19, 31, 0), CFG) == []


def test_cooldown_suppresses_repeat_but_not_other_rule():
    problems = [("nearly_full", "x"), ("filling_fast", "y")]
    last = {"nearly_full": 1000}
    assert rules(disk_check.due(problems, last, 1000 + 5 * 3600, 6)) == ["filling_fast"]
    assert rules(disk_check.due(problems, last, 1000 + 6 * 3600, 6)) == ["nearly_full", "filling_fast"]


def test_parse_du():
    assert disk_check.parse_du("100\t/root/.cache\n300\t/root\n") == {"/root/.cache": 100, "/root": 300}


def test_growth_names_the_deepest_culprit_once():
    before = {"/": 10, "/root": 6, "/root/.cache": 5, "/var": 4}
    after = {"/": 13, "/root": 9, "/root/.cache": 8, "/var": 4}
    # The 3 bytes appear once, against the deepest folder, not also against /root and /.
    assert disk_check.growth_rows(before, after, 10) == [(3, "/root/.cache")]


def test_growth_of_files_directly_in_a_parent_is_labelled():
    before = {"/": 10, "/root": 6, "/root/.cache": 5}
    after = {"/": 12, "/root": 8, "/root/.cache": 5}
    assert disk_check.growth_rows(before, after, 10) == [(2, "/root (files directly inside)")]


def test_new_folder_counts_as_growth():
    assert disk_check.growth_rows({"/": 1}, {"/": 4, "/srv": 3}, 10) == [(3, "/srv")]


def test_unaccounted_bytes():
    assert disk_check.unaccounted_bytes(reading(10, 5), {"/": 7 * GB}, "/") == 3 * GB
