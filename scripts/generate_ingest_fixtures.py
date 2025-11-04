#!/usr/bin/env python3
"""Generate sample ingestion fixtures without checking binaries into git."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yo.sample_files import ensure_ingest_samples


def main() -> None:
    fixtures = ensure_ingest_samples(ROOT / "fixtures" / "ingest")
    for label, path in fixtures.items():
        print(f"Created {label} fixture at {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
