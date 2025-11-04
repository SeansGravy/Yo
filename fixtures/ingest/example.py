"""Example module for Yo ingestion tests."""

from __future__ import annotations


def summarize_phase(phase: str) -> str:
    """Return a short summary for a roadmap phase."""

    phases = {
        "1": "Rich RAG foundation",
        "1.5": "Lite UI bridge",
        "2": "Autonomous workflows",
    }
    return phases.get(phase, "Unknown phase")


if __name__ == "__main__":
    print(summarize_phase("1"))
