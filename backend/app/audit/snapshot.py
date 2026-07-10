"""DecisionSnapshot build + replay (specs/11 §6–§7, HR-5, FR-AUD-5/-6).

replay() re-verifies the pinned pack manifests, rebuilds the evaluation
context from the snapshot's computed values, re-runs the deterministic
rules engine, and diffs rule-by-rule. Calc-level re-derivation (income →
DTI → … from extracted fields) plugs in via `assemble_context` when the
Phase-5 assembly function lands — the SAME function the pipeline uses,
so replay can never drift from production logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from app.audit.canonical import canonical_json, sha256_hex
from app.policy_engine import JsonRulesEngine, load_packs
from app.policy_engine.result import RulesResult

AssembleFn = Callable[[dict], dict]  # snapshot -> evaluation context


def build_snapshot(
    *,
    application_id: str,
    versions: dict[str, Any],
    inputs: dict[str, Any],
    computed: dict[str, Any],
    rules: RulesResult,
    aus: dict[str, Any],
    conditions: list[dict],
    decision: dict[str, Any],
    adverse_action_notice_sha256: str | None = None,
    sealed_at: str | None = None,
) -> tuple[dict, str]:
    """Returns (snapshot dict, sha256 of its canonical JSON)."""
    snapshot = {
        "snapshot_version": "1",
        "application_id": application_id,
        "sealed_at": sealed_at
        or datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "versions": versions,
        "inputs": inputs,
        "computed": computed,
        "rules": {
            "evaluations": [
                {
                    "rule_id": e.rule_id,
                    "outcome": e.outcome,
                    "reason_code": e.reason_code,
                    "inputs": [
                        {"path": i.path, "value": i.value, "lineage_ref": i.lineage_ref}
                        for i in e.inputs
                    ],
                }
                for e in rules.evaluations
            ],
            "overall": rules.overall,
            "counteroffer_hints": [
                {"rule_id": h.rule_id, "parameter": h.parameter,
                 "max_value": h.max_value, "achieved_ratio": h.achieved_ratio}
                for h in rules.counteroffer_hints
            ],
        },
        "aus": aus,
        "conditions": conditions,
        "decision": decision,
        "adverse_action_notice_sha256": adverse_action_notice_sha256,
    }
    return snapshot, sha256_hex(canonical_json(snapshot))


@dataclass(frozen=True)
class ReplayResult:
    identical: bool
    diffs: tuple[str, ...] = field(default_factory=tuple)


def _context_from_snapshot(snapshot: dict) -> dict:
    """Default assembly: rebuild the eval context from the rule inputs the
    sealed run actually consumed (exact values, exact paths)."""
    context: dict[str, tuple[Any, str | None]] = {}
    for evaluation in snapshot["rules"]["evaluations"]:
        for rule_input in evaluation["inputs"]:
            if rule_input["value"] == "<missing>":
                continue
            context[rule_input["path"]] = (
                _coerce(rule_input["value"]), rule_input.get("lineage_ref"),
            )
    return context


def _coerce(value: str) -> Any:
    if value in ("True", "true"):
        return True
    if value in ("False", "false"):
        return False
    try:
        d = Decimal(value)
        return int(d) if d == d.to_integral_value() and "." not in value else d
    except InvalidOperation:
        return value


def replay(
    snapshot: dict,
    *,
    packs_root: Path,
    assemble_context: AssembleFn | None = None,
) -> ReplayResult:
    diffs: list[str] = []
    versions = snapshot["versions"]

    base_dir = packs_root / versions["policy_pack"]
    overlay_dir = packs_root / versions["state_overlay_pack"]
    packs = load_packs(base_dir, overlay_dir)  # re-verifies manifests (HR-7)

    if packs.base_manifest_sha256 != versions["policy_pack_manifest_sha256"]:
        diffs.append(
            f"policy pack manifest drift: {packs.base_manifest_sha256} != "
            f"pinned {versions['policy_pack_manifest_sha256']}"
        )
    if packs.overlay_manifest_sha256 != versions["state_overlay_manifest_sha256"]:
        diffs.append("state overlay manifest drift")
    if diffs:
        return ReplayResult(False, tuple(diffs))

    context = (assemble_context or _context_from_snapshot)(snapshot)
    result = JsonRulesEngine().evaluate(packs, context)

    sealed = {e["rule_id"]: e for e in snapshot["rules"]["evaluations"]}
    replayed = {e.rule_id: e for e in result.evaluations}

    for rule_id, sealed_eval in sealed.items():
        live = replayed.get(rule_id)
        if live is None:
            diffs.append(f"{rule_id}: absent on replay")
            continue
        if live.outcome != sealed_eval["outcome"]:
            diffs.append(
                f"{rule_id}: outcome {sealed_eval['outcome']} -> {live.outcome}")
        if (live.reason_code or None) != (sealed_eval["reason_code"] or None):
            diffs.append(
                f"{rule_id}: reason {sealed_eval['reason_code']} -> {live.reason_code}")
    for rule_id in replayed:
        if rule_id not in sealed:
            diffs.append(f"{rule_id}: new rule on replay (pack drift?)")

    if result.overall != snapshot["rules"]["overall"]:
        diffs.append(
            f"overall: {snapshot['rules']['overall']} -> {result.overall}")

    return ReplayResult(identical=not diffs, diffs=tuple(diffs))


__all__ = ["build_snapshot", "replay", "ReplayResult"]
