"""run() end to end with the disk, du and mail replaced, and a temporary state file."""

import tomllib
from pathlib import Path

import pytest

from vm_ops import disk_alert
from vm_ops.disk_check import GB

CONFIG = Path(__file__).parents[1] / "config.toml"
DAY = 86400
T0 = 20000 * DAY + 4 * 3600   # 04:00 UTC, after the 03:00 snapshot hour


@pytest.fixture
def cfg(tmp_path):
    cfg = tomllib.loads(CONFIG.read_text())
    cfg["paths"]["state_file"] = str(tmp_path / "state.json")
    return cfg


class Fake:
    """Stands in for the disk, du and Gmail, recording what run() asked of them."""

    def __init__(self, used_gb, free_gb, sizes):
        self.used, self.free, self.sizes = used_gb, free_gb, sizes
        self.du_calls, self.mails = 0, []

    def disk(self, path, now):
        return {"time": now, "used": self.used * GB, "free": self.free * GB}

    def du(self, root, depth, timeout):
        self.du_calls += 1
        return dict(self.sizes)

    def mail(self, subject, body, cfg):
        self.mails.append((subject, body))

    def run(self, cfg, now, dry_run=False):
        return disk_alert.run(cfg, now, dry_run, self.disk, self.du, self.mail)


def test_quiet_disk_takes_baseline_and_sends_nothing(cfg):
    fake = Fake(10, 28, {"/": 10 * GB})
    assert fake.run(cfg, T0) == []
    assert fake.du_calls == 1 and fake.mails == []
    fake.run(cfg, T0 + 900)              # same day: no second snapshot
    assert fake.du_calls == 1


def test_alert_email_names_growth_since_baseline_then_cools_down(cfg):
    fake = Fake(10, 28, {"/": 10 * GB, "/root": 2 * GB, "/root/.cache": 1 * GB})
    fake.run(cfg, T0)                    # baseline
    fake.used, fake.free = 34, 4         # 89% used
    fake.sizes = {"/": 34 * GB, "/root": 26 * GB, "/root/.cache": 25 * GB}
    sent = fake.run(cfg, T0 + 900)
    assert [rule for rule, _ in sent] == ["nearly_full", "filling_fast"]
    subject, body = fake.mails[0]
    assert "nearly full, filling fast" in subject
    assert "+24.00 GB  /root/.cache" in body
    fake.run(cfg, T0 + 1800)             # inside the 6 h cooldown
    assert len(fake.mails) == 1


def test_hidden_space_hint(cfg):
    # config.toml checks "/", a mount point, so the df-versus-du comparison applies.
    fake = Fake(36, 0.5, {"/": 30 * GB})
    fake.run(cfg, T0)
    assert "lsof +L1" in fake.mails[0][1]


def test_dry_run_sends_and_saves_nothing(cfg, capsys):
    fake = Fake(36, 0.5, {"/": 36 * GB})
    fake.run(cfg, T0, dry_run=True)
    assert fake.mails == [] and not Path(cfg["paths"]["state_file"]).exists()
    assert "would email" in capsys.readouterr().out


def test_hidden_space_hint_skipped_below_a_mount_point(cfg, tmp_path):
    cfg["disk"]["path"] = str(tmp_path)
    fake = Fake(36, 0.5, {str(tmp_path): 1 * GB})
    fake.run(cfg, T0)
    assert "lsof" not in fake.mails[0][1]
