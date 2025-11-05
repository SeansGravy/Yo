"""Lifecycle management utilities for Yo."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, List

LOG_DIR = Path("data/logs")
SNAPSHOT_DIR = Path("data/snapshots")
CONFIG_FILES = [
    Path("requirements.txt"),
    Path("requirements-lock.txt"),
    Path(".env"),
]
TELEMETRY_FILES = [
    LOG_DIR / "test_summary.json",
    LOG_DIR / "test_history.json",
    LOG_DIR / "dependency_history.json",
    LOG_DIR / "telemetry_summary.json",
]
LIFECYCLE_HISTORY_PATH = LOG_DIR / "lifecycle_history.json"


@dataclass
class SnapshotMetadata:
    name: str
    created_at: str
    files: List[str]
    hash: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "files": self.files,
            "hash": self.hash,
        }


def _load_lifecycle_history() -> list[dict[str, Any]]:
    if not LIFECYCLE_HISTORY_PATH.exists():
        return []
    try:
        return json.loads(LIFECYCLE_HISTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _record_lifecycle_event(action: str, detail: dict[str, Any]) -> None:
    history = _load_lifecycle_history()
    history.append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "detail": detail,
        }
    )
    LIFECYCLE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIFECYCLE_HISTORY_PATH.write_text(json.dumps(history[-200:], indent=2), encoding="utf-8")


def system_clean(dry_run: bool = False, older_than_days: int = 14) -> List[Path]:
    """Remove stale logs and temporary artifacts."""

    removed: List[Path] = []
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    for path in LOG_DIR.glob("yo_test_results_*.log"):
        stat = path.stat()
        if datetime.utcfromtimestamp(stat.st_mtime) < cutoff:
            if not dry_run:
                path.unlink(missing_ok=True)
            removed.append(path)

    lock_path = Path("data/.milvus_lite.db.lock")
    if lock_path.exists():
        if not dry_run:
            lock_path.unlink(missing_ok=True)
        removed.append(lock_path)

    _record_lifecycle_event(
        "clean_preview" if dry_run else "clean",
        {
            "removed": [str(path) for path in removed],
            "older_than_days": older_than_days,
            "count": len(removed),
        },
    )

    return removed


def _hash_files(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        if not path.exists():
            continue
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(8192)
                if not chunk:
                    break
                digest.update(chunk)
    return digest.hexdigest()


def system_snapshot(name: str | None = None, include_logs: bool = True) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    name = name or f"snapshot_{timestamp}"
    snapshot_path = SNAPSHOT_DIR / f"{name}.tar.gz"

    files: List[Path] = []
    for path in CONFIG_FILES + TELEMETRY_FILES:
        if path.exists():
            files.append(path)

    if include_logs:
        for log_path in LOG_DIR.glob("yo_test_results_*.log"):
            files.append(log_path)

    with tarfile.open(snapshot_path, "w:gz") as tar:
        for path in files:
            if path.exists():
                tar.add(path, arcname=str(path))

        metadata = SnapshotMetadata(
            name=name,
            created_at=datetime.utcnow().isoformat(),
            files=[str(path) for path in files],
            hash=_hash_files(files),
        )
        metadata_bytes = json.dumps(metadata.to_dict(), indent=2).encode("utf-8")
        info = tarfile.TarInfo("snapshot_metadata.json")
        info.size = len(metadata_bytes)
        tar.addfile(info, io.BytesIO(metadata_bytes))

    _record_lifecycle_event(
        "snapshot",
        {
            "name": name,
            "path": str(snapshot_path),
            "hash": metadata.hash,
            "file_count": len(files),
        },
    )

    return snapshot_path


def _is_within_directory(directory: Path, target: Path) -> bool:
    try:
        target.relative_to(directory)
        return True
    except ValueError:
        return False


def system_restore(archive: Path, confirm: bool = True) -> List[Path]:
    if confirm:
        response = input(f"⚠️  Restoring from {archive} will overwrite telemetry files. Continue? [y/N] ")
        if response.lower() not in {"y", "yes"}:
            return []

    restored: List[Path] = []
    extract_root = Path(".").resolve()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if member.isdir():
                continue

            relative_path = Path(member.name)
            if relative_path.name == "snapshot_metadata.json":
                destination = (SNAPSHOT_DIR / relative_path.name).resolve()
            else:
                destination = (extract_root / relative_path).resolve()

            if not _is_within_directory(extract_root, destination):
                raise ValueError(f"Unsafe path detected in archive: {member.name}")

            destination.parent.mkdir(parents=True, exist_ok=True)
            handle = tar.extractfile(member)
            if handle is None:
                continue
            with handle:
                with open(destination, "wb") as outfile:
                    shutil.copyfileobj(handle, outfile)
            restored.append(destination)

    if restored:
        _record_lifecycle_event(
            "restore",
            {
                "archive": str(archive),
                "restored": [str(path) for path in restored],
            },
        )

    return restored


def list_snapshots(limit: int | None = None) -> List[dict[str, Any]]:
    snapshots: List[dict[str, Any]] = []
    if not SNAPSHOT_DIR.exists():
        return snapshots

    archives = sorted(SNAPSHOT_DIR.glob("*.tar.gz"))
    if limit is not None and limit > 0:
        archives = archives[-limit:]

    for archive in archives:
        try:
            with tarfile.open(archive, "r:gz") as tar:
                member = tar.getmember("snapshot_metadata.json")
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                with handle:
                    metadata = json.loads(handle.read().decode("utf-8"))
        except Exception:
            continue
        metadata["path"] = str(archive)
        snapshots.append(metadata)
    return snapshots


def load_lifecycle_history(limit: int | None = None) -> List[dict[str, Any]]:
    history = _load_lifecycle_history()
    if limit is not None and limit > 0:
        return history[-limit:]
    return history


__all__ = [
    "system_clean",
    "system_snapshot",
    "system_restore",
    "SnapshotMetadata",
    "list_snapshots",
    "load_lifecycle_history",
]
