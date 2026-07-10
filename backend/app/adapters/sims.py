"""Simulated adapter implementations (specs/03 §6). Deterministic: they
read package data/sidecars only — no network, no clock, no randomness.

The OFAC sim flags any party whose name contains the marker token
"SANCTIONED" (synthetic packages use e.g. "SANCTIONED TEST PARTY" for
archetype fixtures) — a hit suspends the pipeline (FR-VER-5)."""

from __future__ import annotations

from app.adapters.base import AdapterResult


class SimCreditBureau:
    NAME, VERSION = "sim-credit-bureau", "1.0"

    def pull(self, *, package: dict, permissible_purpose: str) -> AdapterResult:
        credit = package["credit"]
        return AdapterResult(self.NAME, self.VERSION, {
            "permissible_purpose": permissible_purpose,
            "report_date": credit["report_date"],
            "borrower_count": len(credit["scores"]),
            "tradeline_count": len(credit["tradelines"]),
            "open_disputes": credit["open_disputes"],
        })


class SimEmploymentVerifier:
    NAME, VERSION = "sim-voe", "1.0"

    def verify(self, *, borrower: dict) -> AdapterResult:
        sidecar = borrower.get("voe_sidecar") or {"result": "unavailable"}
        return AdapterResult(self.NAME, self.VERSION, {
            "borrower_id": borrower["borrower_id"],
            "result": sidecar["result"],
            "verified_start_date": sidecar.get("verified_start_date"),
        })


class SimFloodZone:
    NAME, VERSION = "sim-flood", "1.0"

    def lookup(self, *, property_data: dict) -> AdapterResult:
        zone = property_data.get("flood_zone_sidecar", "X")
        return AdapterResult(self.NAME, self.VERSION, {
            "zone": zone,
            "sfha": zone in ("A", "AE", "AH", "AO", "V", "VE"),
        })


class SimOfacScreen:
    NAME, VERSION = "sim-ofac", "1.0"
    MARKER = "SANCTIONED"

    def screen(self, *, parties: list[str]) -> AdapterResult:
        hits = [p for p in parties if self.MARKER in p.upper()]
        return AdapterResult(self.NAME, self.VERSION, {
            "parties_screened": len(parties),
            "hit": bool(hits),
            "hit_parties": hits,
        })


class SimGeoDistance:
    NAME, VERSION = "sim-geo", "1.0"

    def distance(self, *, property_data: dict, employment: dict) -> AdapterResult:
        miles = employment.get("distance_to_property_miles_sidecar")
        return AdapterResult(self.NAME, self.VERSION, {
            "employer": employment.get("employer"),
            "miles": miles if miles is not None else 0,
            "source": "sidecar" if miles is not None else "default_zero",
        })


__all__ = [
    "SimCreditBureau", "SimEmploymentVerifier", "SimFloodZone",
    "SimOfacScreen", "SimGeoDistance",
]
