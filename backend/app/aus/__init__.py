"""Deterministic DU-style AUS simulator (specs/08). Advisory only (HR-2)."""

from .du_simulator import AusFindings, AusMessage, run_simulator

__all__ = ["run_simulator", "AusFindings", "AusMessage"]
