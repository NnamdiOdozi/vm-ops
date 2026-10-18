"""The pure rules: thresholds, fill rate, cooldown and growth attribution."""

from vm_ops import disk_check
from vm_ops.disk_check import GB

CFG = {"alert_percent": 85, "fill_alert_hours": 24, "fill_window_hours": 6, "min_fill_drop_gb": 5}
H = 3600


def reading(used_gb, free_gb, time=0):
    return {"time": time, "used": used_gb * GB, "free": free_gb * GB}


def rules(problems):
    return [rule for rule, _ in problems]


def test_percent_uses_df_convention():
    # 36 GB used, 0.5 GB writable: df says 99%, not 36/38.
    assert round(disk_check.percent_used(reading(36, 0.5)), 1) == 98.6


def test_nearly_full_triggers_at_threshold_only():
    assert rules(disk_check.disk_problems(reading(85, 15), [], CFG)) == ["nearly_full"]
    assert disk_check.disk_problems(reading(84, 16), [], CFG) == []


def test_filling_fast_when_full_within_window():
    # 6 GB lost in 2 hours = 3 GB/h; 20 GB left -> full in under 7 h, though only 60% used.
    history = [reading(24, 26, 0), reading(26, 24, 1 * H)]
    assert rules(disk_check.disk_problems(reading(30, 20, 2 * H), history, CFG)) == ["filling_fast"]


def test_vscode_login_burst_is_not_an_alert():
    # The 2026-10-18 false alarm: 0.6 GB in 15 minutes, 12 GB left. Under the 5 GB minimum.
    history = [reading(22.4, 12.6, 0)]
    assert disk_check.disk_problems(reading(23, 12, 900), history, CFG) == []


def test_rate_is_measured_over_the_window_not_the_last_step():
    # A 5.5 GB install six hours ago averages to under 1 GB/h; 25 GB left is ~27 h away.
    history = [reading(20, 30.5, 0), reading(25.5, 25, 900)]
    assert disk_check.disk_problems(reading(25.5, 25, 6 * H), history, CFG) == []


def test_readings_older_than_the_window_are_ignored():
    # A 10 GB drop that started 7 hours ago is outside the 6-hour window.
    history = [reading(10, 30, 0), reading(19, 21, 1.5 * H)]
    assert disk_check.disk_problems(reading(20, 20, 7 * H), history, CFG) == []


def test_cooldown_suppresses_repeat_but_not_other_rule():
    problems = [("nearly_full", "x"), ("filling_fast", "y")]
    last = {"nearly_full": 1000}
    assert rules(disk_check.due(problems, last, 1000 + 5 * 3600, 6)) == ["filling_fast"]
    assert rules(disk_check.due(problems, last, 1000 + 6 * 3600, 6)) == ["nearly_full", "filling_fast"]


def test_parse_du():
    assert disk_check.parse_du("100\t/root/.cache\n300\t/root\n") == {"/root/.cache": 100, "/root": 300}


def test_growth_hides_rows_below_the_minimum():
    before = {"/": 10, "/a": 5, "/b": 5}
    after = {"/": 14, "/a": 8, "/b": 6}
    assert disk_check.growth_rows(before, after, 10, min_bytes=2) == [(3, "/a")]


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
