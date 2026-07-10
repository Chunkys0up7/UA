"""Evaluation result types (specs/07 §2/§4, FR-POL-3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Outcome = Literal["pass", "fail", "refer", "not_applicable"]
Overall = Literal["eligible", "ineligible", "refer"]


@dataclass(frozen=True)
class RuleInput:
    path: str
    value: str
    lineage_ref: str | None


@dataclass(frozen=True)
class Artifact:
    id: str
    category: str  # PTA | PTD | PTF
    text_template: str
    rule_id: str


@dataclass(frozen=True)
class CounterofferHint:
    rule_id: str
    parameter: str  # "loan.amount"
    max_value: str
    achieved_ratio: str | None = None


@dataclass(frozen=True)
class RuleEvaluation:
    rule_id: str
    ruleset: str
    pack_version: str
    description: str
    severity: str
    citation: str | None
    inputs: tuple[RuleInput, ...]
    outcome: Outcome
    reason_code: str | None  # set when outcome in (fail, refer)
    note: str | None = None


@dataclass(frozen=True)
class RulesResult:
    pack_version: str
    overlay_pack_version: str
    evaluations: tuple[RuleEvaluation, ...]
    overall: Overall
    failed_rule_ids: tuple[str, ...]
    eligible_reason_codes: tuple[str, ...]
    counteroffer_hints: tuple[CounterofferHint, ...]
    artifacts: tuple[Artifact, ...]  # feeds condition_synthesis (specs/09 §3.8)


@dataclass
class LoadedPacks:
    """Verified pack pair + merged reason codes (specs/17 §3)."""

    base_version: str
    base_manifest_sha256: str
    overlay_version: str
    overlay_manifest_sha256: str
    rules_files: list[dict]          # base rules files (parsed JSON)
    overlay_common: dict | None      # common.rules.json
    overlay_by_state: dict[str, dict]  # "TX" -> parsed rules file
    reason_codes: dict[str, dict]    # merged RC-* -> binding
    compensating_factors: list[dict]
    constants: dict
    states_index: dict
    reference_indices: dict
    vocabulary: frozenset[str] = field(default_factory=frozenset)


__all__ = [
    "Outcome", "Overall", "RuleInput", "Artifact", "CounterofferHint",
    "RuleEvaluation", "RulesResult", "LoadedPacks",
]
