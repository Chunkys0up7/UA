"""DU-style scorer (specs/08, FR-AUS-1..4). Deterministic mapping from the
risk profile to a recommendation + verification messages; config-driven
from policy/aus/du-sim.v1.json (version pinned in every snapshot)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.domain.numeric import D

RECOMMENDATIONS = ("Approve/Eligible", "Approve/Ineligible",
                   "Refer with Caution", "Out of Scope")


@dataclass(frozen=True)
class AusMessage:
    message_id: str
    category: str  # PTA | PTD | PTF
    text: str


@dataclass(frozen=True)
class AusFindings:
    recommendation: str
    simulator_version: str
    breakdown: dict[str, int]
    total_points: int
    messages: tuple[AusMessage, ...]


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _band_points(spec: dict, value: Decimal | int) -> int:
    kind = spec["kind"]
    bands = spec["bands"]
    v = D(str(value))
    if kind == "bands_desc_gte":
        for bound, points in bands:
            if v >= D(str(bound)):
                return points
        return bands[-1][1]
    # bands_asc_lte
    for bound, points in bands:
        if v <= D(str(bound)):
            return points
    return bands[-1][1]


def run_simulator(
    config: dict,
    *,
    credit_score: int,
    back_dti: str,
    ltv: str,
    reserves_months: str,
    self_employed: bool,
    occupancy: str,
    red_flag_counts: dict[str, int],   # {"elevated": n, "critical": n}
    rules_rollup: str,                 # eligible | ineligible | refer
    triggers: dict[str, Any],          # message-trigger facts (specs/08 §4)
) -> AusFindings:
    factors = config["risk_factors"]
    breakdown = {
        "credit_score": _band_points(factors["credit_score"], credit_score),
        "back_dti": _band_points(factors["back_dti"], D(back_dti)),
        "ltv": _band_points(factors["ltv"], D(ltv)),
        "reserves_months": _band_points(factors["reserves_months"],
                                        D(reserves_months)),
        "self_employed": factors["self_employed"]["true" if self_employed else "false"],
        "occupancy": factors["occupancy"]["values"][occupancy],
        "red_flags": (red_flag_counts.get("elevated", 0)
                      * factors["red_flag_elevated_each"]
                      + red_flag_counts.get("critical", 0)
                      * factors["red_flag_critical_each"]),
    }
    total = sum(breakdown.values())
    thresholds = config["thresholds"]

    if rules_rollup == "ineligible":
        recommendation = "Approve/Ineligible"
    elif total <= thresholds["approve_max"] and rules_rollup == "eligible":
        recommendation = "Approve/Eligible"
    elif total <= thresholds["refer_max"]:
        recommendation = "Refer with Caution"
    else:
        recommendation = "Out of Scope"
    if red_flag_counts.get("critical", 0) and recommendation in (
            "Approve/Eligible",):
        recommendation = config.get("critical_flag_floor", "Refer with Caution")

    messages: list[AusMessage] = []
    for spec in config["messages"]:
        trigger = spec["trigger"]
        fires = trigger == "always" or bool(triggers.get(trigger))
        if fires:
            text = spec["template"]
            for key, value in (triggers.get(trigger) or {}).items() \
                    if isinstance(triggers.get(trigger), dict) else []:
                text = text.replace("{" + key + "}", str(value))
            messages.append(AusMessage(spec["message_id"], spec["category"], text))

    return AusFindings(
        recommendation=recommendation,
        simulator_version=config["simulator_version"],
        breakdown=breakdown, total_points=total, messages=tuple(messages),
    )


__all__ = ["run_simulator", "AusFindings", "AusMessage", "load_config",
           "RECOMMENDATIONS"]
