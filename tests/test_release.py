from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from yo import release


def test_build_release_bundle_requires_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        release.build_release_bundle()


def test_verify_integrity_manifest_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = tmp_path / "data/logs/integrity_manifest.json"
    result = release.verify_integrity_manifest(manifest_path)
    assert result["success"] is False
    assert "manifest" not in result or result["manifest"] is None


def test_verify_integrity_manifest_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    logs_dir = Path("data/logs")
    checksums_dir = logs_dir / "checksums"
    checksums_dir.mkdir(parents=True, exist_ok=True)

    checksum_path = checksums_dir / "artifact_hashes.txt"
    checksum_path.write_text("abc123\n", encoding="utf-8")
    signature_path = checksums_dir / "artifact_hashes.sig"
    signature_path.write_text("signature", encoding="utf-8")
    key_path = checksums_dir / "artifact_signing_public.asc"
    key_path.write_text("public-key", encoding="utf-8")
    ledger_path = logs_dir / "verification_ledger.jsonl"
    ledger_path.write_text('{"version": "v0.5.0"}\n', encoding="utf-8")
    audit_path = logs_dir / "audit_report.md"
    audit_path.write_text("# Audit\n", encoding="utf-8")
    telemetry_path = logs_dir / "telemetry_summary.json"
    telemetry_path.write_text("{}", encoding="utf-8")

    releases_dir = Path("releases")
    releases_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = releases_dir / "release_v0.5.0.tar.gz"
    bundle_path.write_bytes(b"bundle-bytes")
    bundle_checksum = hashlib.sha256(b"bundle-bytes").hexdigest()
    bundle_sig = releases_dir / "release_v0.5.0.tar.gz.sig"
    bundle_sig.write_text("bundle-sig", encoding="utf-8")

    manifest_path = logs_dir / "integrity_manifest.json"
    manifest = {
        "version": "v0.5.0",
        "commit": "abc1234",
        "timestamp": "2025-11-07T00:00:00Z",
        "health": 98.5,
        "artifact_checksum": str(checksum_path),
        "artifact_signature": str(signature_path),
        "artifact_signing_key": str(key_path),
        "ledger_entry": str(ledger_path),
        "audit_report": str(audit_path),
        "telemetry_summary": str(telemetry_path),
        "release_bundle": str(bundle_path),
        "bundle_signature": str(bundle_sig),
        "bundle_checksum": bundle_checksum,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    version_manifest_path = Path("releases") / f"{release.RELEASE_MANIFEST_PREFIX}v0.5.0.json"
    version_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(
        release,
        "verify_signature",
        lambda signature_path, target_path, key_path=None: {"success": True},
    )

    result = release.verify_integrity_manifest(manifest_path)
    assert result["success"] is True
    assert result["checksum_valid"] is True

    manifests = release.list_release_manifests(release_dir="releases")
    assert manifests and manifests[0]["version"] == "v0.5.0"

    loaded = release.load_release_manifest("v0.5.0", release_dir="releases", manifest_path=manifest_path)
    assert loaded is not None and loaded["version"] == "v0.5.0"
