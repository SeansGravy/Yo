"""Utilities for signing and verifying files with GnuPG."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


def _gpg_path() -> str | None:
    return os.environ.get("GPG") or shutil.which("gpg")


def _parse_signer(output: str) -> str | None:
    match = re.search(r'Good signature from "([^"]+)"', output)
    if match:
        return match.group(1)
    return None


def verify_signature(
    signature_path: Path | str,
    target_path: Path | str,
    *,
    key_path: Path | str | None = None,
) -> dict[str, Any]:
    """Verify ``signature_path`` against ``target_path`` using GnuPG."""

    signature = Path(signature_path)
    target = Path(target_path)
    key = Path(key_path) if key_path is not None else None

    result: dict[str, Any] = {
        "success": False,
        "signer": None,
        "message": "",
        "signature": str(signature),
        "target": str(target),
        "timestamp": datetime.utcnow().isoformat(),
    }

    if not signature.exists() or not target.exists():
        result["message"] = "Signature or target file is missing."
        return result

    gpg_bin = _gpg_path()
    if not gpg_bin:
        result["message"] = "gpg executable not found. Install GnuPG to verify signatures."
        return result

    env = os.environ.copy()
    with tempfile.TemporaryDirectory() as gnupg_home:
        env["GNUPGHOME"] = gnupg_home
        env.setdefault("GPG_TTY", "")

        if key is not None and key.exists():
            import_proc = subprocess.run(
                [gpg_bin, "--batch", "--yes", "--import", str(key)],
                capture_output=True,
                text=True,
                env=env,
            )
            if import_proc.returncode != 0:
                result["message"] = import_proc.stderr or import_proc.stdout or "Failed to import signing key."
                return result

        verify_proc = subprocess.run(
            [gpg_bin, "--batch", "--verify", str(signature), str(target)],
            capture_output=True,
            text=True,
            env=env,
        )

        output = "".join(filter(None, [verify_proc.stdout, verify_proc.stderr])).strip()
        result.update(
            {
                "success": verify_proc.returncode == 0,
                "signer": _parse_signer(output),
                "message": output,
            }
        )
        return result


def sign_file(
    target_path: Path | str,
    signature_path: Path | str,
    *,
    signer: str | None = None,
    armor: bool = True,
) -> dict[str, Any]:
    """Sign ``target_path`` writing the detached signature to ``signature_path``."""

    target = Path(target_path)
    signature = Path(signature_path)

    result: dict[str, Any] = {
        "success": False,
        "message": "",
        "signature": str(signature),
        "target": str(target),
    }

    if not target.exists():
        result["message"] = f"Target file not found: {target}"
        return result

    gpg_bin = _gpg_path()
    if not gpg_bin:
        result["message"] = "gpg executable not found. Install GnuPG to sign releases."
        return result

    args = [gpg_bin, "--batch", "--yes", "--detach-sig"]
    if armor:
        args.append("--armor")
    if signer:
        args.extend(["--local-user", signer])
    args.extend(["--output", str(signature), str(target)])

    sign_proc = subprocess.run(args, capture_output=True, text=True)
    output = "".join(filter(None, [sign_proc.stdout, sign_proc.stderr])).strip()
    result.update({"success": sign_proc.returncode == 0, "message": output})
    if result["success"] and not signature.exists():
        result["success"] = False
        result["message"] = (
            output or "Signature command reported success but the signature file was not created."
        )
    return result
