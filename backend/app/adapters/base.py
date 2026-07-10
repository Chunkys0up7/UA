"""Adapter protocols (specs/03 §6). Results carry adapter name + version
for the audit trail and the DecisionSnapshot (FR-VER-4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterResult:
    adapter_name: str
    adapter_version: str
    result: dict[str, Any]

    def audit_payload(self, request_summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter_name": self.adapter_name,
            "adapter_version": self.adapter_version,
            "request_summary": request_summary,
            "result_summary": self.result,
        }


class CreditBureauAdapter(Protocol):
    def pull(self, *, package: dict, permissible_purpose: str) -> AdapterResult: ...


class EmploymentVerifier(Protocol):
    def verify(self, *, borrower: dict) -> AdapterResult: ...


class FloodZoneService(Protocol):
    def lookup(self, *, property_data: dict) -> AdapterResult: ...


class OfacScreen(Protocol):
    def screen(self, *, parties: list[str]) -> AdapterResult: ...


class GeoDistanceAdapter(Protocol):
    def distance(self, *, property_data: dict, employment: dict) -> AdapterResult: ...


__all__ = [
    "AdapterResult", "CreditBureauAdapter", "EmploymentVerifier",
    "FloodZoneService", "OfacScreen", "GeoDistanceAdapter",
]
