"""Helpers for packaging and verifying Yo release bundles."""

from __future__ import annotations

import json
import os
import tarfile
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from yo.signing import sign_file, verify_signature
from yo.telemetry import build_telemetry_summary, load_telemetry_summary


REQUIRED_ARTIFACTS = [
    Path("data/logs/checksums/artifact_hashes.txt"),
    Path("data/logs/checksums/artifact_hashes.sig"),
    Path("data/logs/checksums/artifact_signing_public.asc"),
    Path("data/logs/verification_ledger.jsonl"),
    Path("data/logs/audit_report.md"),
    Path("data/logs/telemetry_summary.json"),
]

OPTIONAL_ARTIFACTS = [
    Path("data/logs/test_summary.json"),
    Path("data/logs/test_history.json"),
    Path("docs/CHANGELOG.md"),
]

DEFAULT_RELEASE_DIR = Path("releases")
DEFAULT_MANIFEST_PATH = Path("data/logs/integrity_manifest.json")


def _run_git(args: list[str]) -> str | None:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return proc.stdout.strip() or None


def detect_version() -> str:
    env_version = os.environ.get("YO_VERSION")
    if env_version:
        return env_version
    version = _run_git(["git", "describe", "--tags", "--abbrev=0"])
    return version or "unreleased"


def detect_commit() -> str:
    commit = _run_git(["git", "rev-parse", "HEAD"])
    return commit or "unknown"


def load_integrity_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> dict[str, Any] | None:
    manifest_path = Path(path)
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _ensure_artifacts_exists(paths: list[Path]) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Required artifacts are missing:\n" + "\n".join(f"- {item}" for item in missing)
        )


def _add_to_archive(tar: tarfile.TarFile, path: Path) -> None:
    arcname = str(path)
    tar.add(str(path), arcname=arcname)


def _bundle_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release_bundle(
    *,
    version: str | None = None,
    signer: str | None = None,
    release_dir: Path | str = DEFAULT_RELEASE_DIR,
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Create a compressed release bundle and associated integrity manifest."""

    required_paths = list(REQUIRED_ARTIFACTS)
    _ensure_artifacts_exists(required_paths)

    release_dir = Path(release_dir)
    manifest_path = Path(manifest_path)
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    version_value = version or detect_version()
    commit_value = detect_commit()
    timestamp = datetime.utcnow().isoformat()

    bundle_name = f"release_{version_value}.tar.gz"
    bundle_path = release_dir / bundle_name
    if bundle_path.exists():
        bundle_path.unlink()

    with tarfile.open(bundle_path, "w:gz") as tar:
        for path in required_paths + [p for p in OPTIONAL_ARTIFACTS if p.exists()]:
            _add_to_archive(tar, path)

    bundle_checksum = _bundle_checksum(bundle_path)
    signature_path = bundle_path.with_suffix(bundle_path.suffix + ".sig")
    sign_result = sign_file(bundle_path, signature_path, signer=signer, armor=False)
    if not sign_result.get("success"):
        if bundle_path.exists():
            bundle_path.unlink(missing_ok=True)  # type: ignore[attr-defined]
        raise RuntimeError(sign_result.get("message") or "Failed to sign release bundle.")

    telemetry_summary = load_telemetry_summary() or build_telemetry_summary()
    health_score = telemetry_summary.get("health_score") or telemetry_summary.get("score")

    manifest: dict[str, Any] = {
        "version": version_value,
        "commit": commit_value,
        "timestamp": timestamp,
        "health": health_score,
        "artifact_checksum": str(REQUIRED_ARTIFACTS[0]),
        "artifact_signature": str(REQUIRED_ARTIFACTS[1]),
        "artifact_signing_key": str(REQUIRED_ARTIFACTS[2]),
        "ledger_entry": str(REQUIRED_ARTIFACTS[3]),
        "audit_report": str(REQUIRED_ARTIFACTS[4]),
        "telemetry_summary": str(REQUIRED_ARTIFACTS[5]),
        "release_bundle": str(bundle_path),
        "bundle_signature": str(signature_path),
        "bundle_checksum": bundle_checksum,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "bundle": str(bundle_path),
        "signature": str(signature_path),
        "manifest": str(manifest_path),
        "manifest_data": manifest,
    }


def verify_integrity_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Verify the integrity manifest and associated artifacts."""

    manifest_path = Path(path)
    manifest = load_integrity_manifest(manifest_path)
    if manifest is None:
        return {
            "success": False,
            "errors": ["Integrity manifest missing or invalid JSON."],
            "manifest_path": str(manifest_path),
        }

    errors: list[str] = []

    def _check_exists(label: str) -> tuple[str, bool]:
        raw = manifest.get(label)
        path = Path(str(raw)) if raw else None
        exists = path is not None and path.exists()
        if not exists:
            errors.append(f"{label.replace('_', ' ').title()} missing ({raw}).")
        return (str(raw) if raw else "", exists)

    files = {
        "artifact_checksum": _check_exists("artifact_checksum"),
        "artifact_signature": _check_exists("artifact_signature"),
        "artifact_signing_key": _check_exists("artifact_signing_key"),
        "ledger_entry": _check_exists("ledger_entry"),
        "audit_report": _check_exists("audit_report"),
        "telemetry_summary": _check_exists("telemetry_summary"),
        "release_bundle": _check_exists("release_bundle"),
        "bundle_signature": _check_exists("bundle_signature"),
    }

    checksum_valid = False
    if files["release_bundle"][1]:
        expected_checksum = manifest.get("bundle_checksum")
        bundle_path = Path(files["release_bundle"][0])
        actual_checksum = _bundle_checksum(bundle_path)
        checksum_valid = bool(expected_checksum) and expected_checksum == actual_checksum
        if not checksum_valid:
            errors.append("Bundle checksum mismatch.")

    artifact_signature_result: dict[str, Any] | None = None
    if files["artifact_signature"][1] and files["artifact_checksum"][1]:
        artifact_signature_result = verify_signature(
            Path(files["artifact_signature"][0]),
            Path(files["artifact_checksum"][0]),
            key_path=files["artifact_signing_key"][0],
        )
        if not artifact_signature_result.get("success"):
            errors.append("Artifact checksum signature invalid.")

    bundle_signature_result: dict[str, Any] | None = None
    if files["bundle_signature"][1] and files["release_bundle"][1]:
        bundle_signature_result = verify_signature(
            Path(files["bundle_signature"][0]),
            Path(files["release_bundle"][0]),
            key_path=files["artifact_signing_key"][0],
        )
        if not bundle_signature_result.get("success"):
            errors.append("Release bundle signature invalid.")

    success = not errors

    return {
        "success": success,
        "errors": errors,
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "files": {key: {"path": value[0], "exists": value[1]} for key, value in files.items()},
        "artifact_signature": artifact_signature_result,
        "bundle_signature": bundle_signature_result,
        "checksum_valid": checksum_valid,
    }
