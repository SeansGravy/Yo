from __future__ import annotations

import json

from yo import deps


def test_deps_diff_detects_drift_and_records_event(tmp_path, monkeypatch) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("packageA==1.0\npackageB==2.0\n", encoding="utf-8")

    lockfile = tmp_path / "requirements-lock.txt"
    lockfile.write_text("packageB==1.5\npackageC==3.0\n", encoding="utf-8")

    history_path = tmp_path / "dependency_history.json"

    monkeypatch.setattr(deps, "REQUIREMENTS_PATH", requirements)
    monkeypatch.setattr(deps, "REQUIREMENTS_LOCK_PATH", lockfile)
    monkeypatch.setattr(deps, "DEPENDENCY_HISTORY_PATH", history_path)

    diff = deps.deps_diff()

    assert diff["added"] == {"packagea": "1.0"}
    assert diff["removed"] == {"packagec": "3.0"}
    assert diff["changed"] == {"packageb": {"requirements": "2.0", "lock": "1.5"}}

    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert history[-1]["action"] == "drift"
    assert set(history[-1]["packages"]) == {"packagea", "packageb", "packagec"}

    lockfile.write_text("packageA==1.0\npackageB==2.0\n", encoding="utf-8")
    diff_after_sync = deps.deps_diff()
    assert diff_after_sync == {"added": {}, "removed": {}, "changed": {}}

    history_after = json.loads(history_path.read_text(encoding="utf-8"))
    assert len(history_after) == len(history)
