"""Simulated external integrations behind Protocols (specs/03 §6,
FR-VER-4/-5). Real vendors replace sims on the internal network without
touching callers. Every result is audited as an adapter_call event."""

from .base import (
    AdapterResult,
    CreditBureauAdapter,
    EmploymentVerifier,
    FloodZoneService,
    GeoDistanceAdapter,
    OfacScreen,
)
from .sims import (
    SimCreditBureau,
    SimEmploymentVerifier,
    SimFloodZone,
    SimGeoDistance,
    SimOfacScreen,
)

__all__ = [
    "AdapterResult", "CreditBureauAdapter", "EmploymentVerifier",
    "FloodZoneService", "OfacScreen", "GeoDistanceAdapter",
    "SimCreditBureau", "SimEmploymentVerifier", "SimFloodZone",
    "SimOfacScreen", "SimGeoDistance",
]
