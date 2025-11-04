"""Yo package utilities."""

from __future__ import annotations

import warnings

warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API",
    module="milvus_lite",
)

__all__: list[str] = []
