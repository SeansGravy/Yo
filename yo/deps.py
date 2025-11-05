"""Dependency intelligence utilities for Yo."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

LOGS_DIR = Path("data/logs")
SUMMARY_PATH = LOGS_DIR / "test_summary.json"
DEPENDENCY_HISTORY_PATH = LOGS_DIR / "dependency_history.json"
REQUIREMENTS_PATH = Path("requirements.txt")
REQUIREMENTS_LOCK_PATH = Path("requirements-lock.txt")

PACKAGE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]")


def _ensure_logs_dir() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR


def _load_json(path: Path) -> object:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_latest_summary() -> Dict[str, object]:
    data = _load_json(SUMMARY_PATH)
    return data if isinstance(data, dict) else {}


def _record_dependency_event(action: str, packages: Sequence[str]) -> None:
    if not packages:
        return
    history = _load_json(DEPENDENCY_HISTORY_PATH)
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "packages": list(packages),
        }
    )
    _save_json(DEPENDENCY_HISTORY_PATH, history)


def _run_pip(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "pip", *args]
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _format_package_name(module_name: str) -> str:
    package = module_name.replace("_", "-")
    package = PACKAGE_NAME_PATTERN.sub("-", package)
    return package.lower()


def deps_check(print_output: bool = True) -> Dict[str, object]:
    """Inspect the current environment and return dependency diagnostics."""

    _ensure_logs_dir()
    summary = _load_latest_summary()
    missing_modules: List[str] = list(summary.get("missing_modules", []) or [])

    if print_output:
        if missing_modules:
            print("⚠️  Missing modules detected in recent telemetry:")
            for module in missing_modules:
                print(f"   • {module}")
        else:
            print("✅ No missing modules recorded in telemetry.")

    pip_check = _run_pip(["check"])
    pip_check_output = pip_check.stdout.strip() or pip_check.stderr.strip()
    if print_output:
        if pip_check.returncode == 0:
            print("✅ `pip check` reports no conflicts.")
        else:
            print("⚠️  `pip check` detected issues:")
            print(pip_check_output)

    diagnostics = {
        "missing_modules": missing_modules,
        "pip_check_status": pip_check.returncode,
        "pip_check_output": pip_check_output,
    }
    return diagnostics


def _query_package_version(package: str) -> str | None:
    info = _run_pip(["show", package])
    if info.returncode != 0:
        return None
    for line in info.stdout.splitlines():
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return None


def _ensure_requirement_entry(package: str, version: str) -> None:
    if not REQUIREMENTS_PATH.exists():
        REQUIREMENTS_PATH.write_text(f"{package}=={version}\n", encoding="utf-8")
        return

    lines = REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
    lower_package = package.lower()
    found = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        normalized = stripped.split("[", 1)[0].strip()
        normalized = re.split(r"[<>=~! ]", normalized, 1)[0]
        if normalized.lower() == lower_package:
            lines[idx] = f"{package}=={version}"
            found = True
            break
    if not found:
        lines.append(f"{package}=={version}")
    REQUIREMENTS_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def deps_freeze() -> Path:
    """Write a snapshot of installed packages to requirements-lock.txt."""

    freeze = _run_pip(["freeze"])
    if freeze.returncode != 0:
        raise RuntimeError(f"pip freeze failed: {freeze.stderr.strip()}")
    REQUIREMENTS_LOCK_PATH.write_text(freeze.stdout, encoding="utf-8")
    print(f"✅ Wrote requirements lockfile to {REQUIREMENTS_LOCK_PATH}")
    return REQUIREMENTS_LOCK_PATH


def deps_repair() -> Dict[str, object]:
    diagnostics = deps_check(print_output=False)
    missing_modules: Iterable[str] = diagnostics.get("missing_modules", []) or []
    missing_modules = list(dict.fromkeys(missing_modules))

    if not missing_modules:
        print("✅ No missing modules to repair.")
        return diagnostics

    repaired: List[str] = []
    failed: List[str] = []

    for module in missing_modules:
        package = _format_package_name(module)
        print(f"🔧 Installing {package} (derived from module '{module}')...")
        install = _run_pip(["install", package])
        if install.returncode != 0:
            print(f"❌ Failed to install {package}: {install.stderr.strip()}")
            failed.append(package)
            continue
        version = _query_package_version(package) or ""
        if version:
            _ensure_requirement_entry(package, version)
        repaired.append(f"{package}=={version}" if version else package)

    if repaired:
        _record_dependency_event("repair", repaired)
        deps_freeze()

    if failed:
        print("⚠️  Some packages could not be installed:")
        for pkg in failed:
            print(f"   • {pkg}")
    else:
        print("✅ Dependency repair completed.")

    diagnostics["repaired"] = repaired
    diagnostics["failed"] = failed
    return diagnostics


def deps_check_command(_: object = None) -> Dict[str, object]:
    return deps_check(print_output=True)


def deps_repair_command(_: object = None) -> Dict[str, object]:
    return deps_repair()


def deps_freeze_command(_: object = None) -> Path:
    return deps_freeze()


def _load_requirements(path: Path) -> Dict[str, str]:
    packages: Dict[str, str] = {}
    if not path.exists():
        return packages
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "==" in stripped:
            name, version = stripped.split("==", 1)
            packages[name.lower()] = version
        else:
            packages[stripped.lower()] = ""
    return packages


def deps_diff() -> Dict[str, Dict[str, str]]:
    requirements = _load_requirements(REQUIREMENTS_PATH)
    lock = _load_requirements(REQUIREMENTS_LOCK_PATH)
    added = {pkg: version for pkg, version in requirements.items() if pkg not in lock}
    removed = {pkg: version for pkg, version in lock.items() if pkg not in requirements}
    changed = {
        pkg: {"requirements": requirements[pkg], "lock": lock[pkg]}
        for pkg in requirements
        if pkg in lock and requirements[pkg] != lock[pkg]
    }
    if added or removed or changed:
        _record_dependency_event(
            "drift",
            list(added.keys()) + list(changed.keys()) + list(removed.keys()),
        )
    return {"added": added, "removed": removed, "changed": changed}


def deps_sync() -> int:
    if not REQUIREMENTS_LOCK_PATH.exists():
        raise FileNotFoundError("requirements-lock.txt not found. Run `yo deps freeze` first.")
    proc = _run_pip(["install", "-r", str(REQUIREMENTS_LOCK_PATH)])
    if proc.returncode == 0:
        _record_dependency_event("sync", ["requirements-lock.txt"])
    else:
        print(proc.stderr.strip())
    return proc.returncode


def deps_diff_command(_: object = None) -> Dict[str, Dict[str, str]]:
    diff = deps_diff()
    if not diff["added"] and not diff["removed"] and not diff["changed"]:
        print("✅ requirements.txt matches requirements-lock.txt")
    else:
        if diff["added"]:
            print("⚠️  Packages in requirements.txt missing from lock:")
            for pkg, version in diff["added"].items():
                print(f"   • {pkg} ({version})")
        if diff["removed"]:
            print("⚠️  Packages in lock missing from requirements.txt:")
            for pkg, version in diff["removed"].items():
                print(f"   • {pkg} ({version})")
        if diff["changed"]:
            print("⚠️  Version differences detected:")
            for pkg, versions in diff["changed"].items():
                print(f"   • {pkg}: requirements={versions['requirements']} lock={versions['lock']}")
    return diff


def deps_sync_command(_: object = None) -> int:
    return deps_sync()


__all__ = [
    "deps_check",
    "deps_repair",
    "deps_freeze",
    "deps_check_command",
    "deps_repair_command",
    "deps_freeze_command",
    "deps_diff",
    "deps_sync",
    "deps_diff_command",
    "deps_sync_command",
]
