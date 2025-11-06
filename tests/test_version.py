from __future__ import annotations

import yo


def test_version_constant() -> None:
    assert hasattr(yo, "__version__")
    assert yo.__version__ == "0.6.0.0"
