"""JsonRulesEngine (specs/07 §2/§4, specs/17 §3, FR-POL-1/-3/-7/-8).

Deterministic by construction: same context + same packs => identical
RulesResult, byte-for-byte. The engine never reads the clock, network,
or filesystem (packs arrive pre-loaded via `LoadedPacks`).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Protocol

from app.domain.numeric import D
from app.policy_engine.ast import Evaluator, MissingInput
from app.policy_engine.result import (
    Artifact,
    CounterofferHint,
    LoadedPacks,
    Outcome,
    RuleEvaluation,
    RuleInput,
    RulesResult,
)

# Recompute callback for counteroffer search: (context, candidate_amount)
# -> updated context (recomputed dti/ltv keys). Injected pure calculators.
RecomputeFn = Callable[[dict[str, tuple[Any, str | None]], Decimal],
                       dict[str, tuple[Any, str | None]]]

Context = dict[str, tuple[Any, str | None]]


class RulesEngine(Protocol):
    def evaluate(self, packs: LoadedPacks, context: Context,
                 recompute: RecomputeFn | None = None) -> RulesResult: ...


class JsonRulesEngine:
    """The shipped RulesEngine implementation (ADR: chosen over GoRules ZEN
    because traces must be lineage-shaped — specs/07 §2)."""

    def evaluate(
        self,
        packs: LoadedPacks,
        context: Context,
        recompute: RecomputeFn | None = None,
    ) -> RulesResult:
        evaluations: list[RuleEvaluation] = []
        hints: list[CounterofferHint] = []
        artifacts: list[Artifact] = []

        rule_files = list(packs.rules_files)
        if packs.overlay_common:
            rule_files.append(packs.overlay_common)
        state = context.get("property.state", (None, None))[0]
        if state and str(state) in packs.overlay_by_state:
            rule_files.append(packs.overlay_by_state[str(state)])

        for rules_file in rule_files:
            pack_version = (
                packs.overlay_version
                if rules_file.get("pack", "").startswith("state-overlays")
                else packs.base_version
            )
            tables = rules_file.get("tables", {})
            derived = rules_file.get("derived_inputs", {})
            for rule in rules_file["rules"]:
                evaluation, hint, rule_artifacts = self._evaluate_rule(
                    rule, rules_file["ruleset"], pack_version,
                    context, tables, derived, recompute,
                )
                evaluations.append(evaluation)
                if hint:
                    hints.append(hint)
                artifacts.extend(rule_artifacts)

        overall = self._rollup(evaluations)
        failed = tuple(e.rule_id for e in evaluations if e.outcome in ("fail", "refer"))
        eligible_codes = tuple(dict.fromkeys(  # de-dup preserving order
            e.reason_code for e in evaluations
            if e.outcome in ("fail", "refer") and e.reason_code
        ))
        return RulesResult(
            pack_version=packs.base_version,
            overlay_pack_version=packs.overlay_version,
            evaluations=tuple(evaluations),
            overall=overall,
            failed_rule_ids=failed,
            eligible_reason_codes=eligible_codes,
            counteroffer_hints=tuple(hints),
            artifacts=tuple(artifacts),
        )

    # ------------------------------------------------------------------
    def _evaluate_rule(
        self,
        rule: dict,
        ruleset: str,
        pack_version: str,
        context: Context,
        tables: dict,
        derived: dict,
        recompute: RecomputeFn | None,
    ) -> tuple[RuleEvaluation, CounterofferHint | None, list[Artifact]]:
        base = dict(
            rule_id=rule["id"], ruleset=ruleset, pack_version=pack_version,
            description=rule["description"], severity=rule["severity"],
            citation=rule.get("citation"),
        )
        artifacts: list[Artifact] = []

        # Guard (specs/17 §7.1): applies false => not_applicable. Guard-
        # consumed inputs are recorded in the trace — the record must show
        # WHY the rule didn't bind, and replay rebuilds its context from
        # recorded inputs (specs/11 §7).
        guard_consumed: dict[str, RuleInput] = {}
        if "applies" in rule:
            guard = Evaluator(context, tables, derived)
            try:
                applicable = guard.evaluate(rule["applies"])
            except MissingInput:
                applicable = False
            guard_consumed = guard.consumed
            if not applicable:
                return (
                    RuleEvaluation(**base, inputs=tuple(guard_consumed.values()),
                                   outcome="not_applicable", reason_code=None),
                    None, [],
                )

        # artifact_always fires whenever the guard matched (specs/17 §7.1).
        if "artifact_always" in rule:
            a = rule["artifact_always"]
            artifacts.append(Artifact(a["id"], a["category"], a["text_template"],
                                      rule["id"]))

        evaluator = Evaluator(context, tables, derived)
        try:
            passed = evaluator.evaluate(rule["when"])
        except MissingInput as missing:
            inputs = tuple({**guard_consumed, **evaluator.consumed}.values()) + (
                RuleInput(missing.path, "<missing>", None),
            )
            return (
                RuleEvaluation(**base, inputs=inputs, outcome="refer",
                               reason_code="RC-DATA-MISSING",
                               note=f"missing input: {missing.path}"),
                None, artifacts,
            )

        inputs = tuple({**guard_consumed, **evaluator.consumed}.values())
        if passed:
            return (
                RuleEvaluation(**base, inputs=inputs, outcome="pass",
                               reason_code=None),
                None, artifacts,
            )

        on_fail = rule["on_fail"]
        outcome: Outcome = "fail" if on_fail["outcome"] == "ineligible" else "refer"
        if "artifact" in on_fail:
            a = on_fail["artifact"]
            artifacts.append(Artifact(a["id"], a["category"], a["text_template"],
                                      rule["id"]))
        hint = None
        if "counteroffer" in on_fail:
            hint = self._solve_counteroffer(
                rule["id"], on_fail["counteroffer"], context, tables, derived,
                recompute,
            )
        return (
            RuleEvaluation(**base, inputs=inputs, outcome=outcome,
                           reason_code=on_fail["reason_code"],
                           note=on_fail.get("note")),
            hint, artifacts,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _rollup(evaluations: list[RuleEvaluation]) -> str:
        """specs/07 §4.4 — only eligibility-severity failures affect rollup."""
        eligibility = [e for e in evaluations if e.severity == "eligibility"]
        if any(e.outcome == "fail" for e in eligibility):
            return "ineligible"
        if any(e.outcome == "refer" for e in eligibility):
            return "refer"
        return "eligible"

    # ------------------------------------------------------------------
    def _solve_counteroffer(
        self,
        rule_id: str,
        spec: dict,
        context: Context,
        tables: dict,
        derived: dict,
        recompute: RecomputeFn | None,
    ) -> CounterofferHint | None:
        solve_for = spec["solve_for"]  # "loan.amount"
        target = spec["target"]

        # Direct bound on the solve_for path itself -> exact (specs/07 §4.3).
        op, args = next(iter(target.items()))
        if (
            op in ("<=", "<")
            and isinstance(args, list)
            and args[0] == solve_for
        ):
            evaluator = Evaluator(context, tables, derived)
            try:
                bound = evaluator.resolve(args[1])
            except MissingInput:
                return None
            return CounterofferHint(rule_id, solve_for,
                                    str(D(str(bound)).quantize(D("0.01"))))

        if recompute is None:
            return None

        # Binary search largest $1,000 multiple satisfying the target.
        current = D(str(context[solve_for][0]))
        lo, hi = Decimal("0"), (current // 1000) * 1000
        best: Decimal | None = None
        while lo <= hi:
            mid = ((lo + hi) / 2).quantize(Decimal("1"))
            candidate = (mid // 1000) * 1000
            trial = recompute(context, candidate)
            evaluator = Evaluator(trial, tables, derived)
            try:
                ok = evaluator.evaluate(target)
            except MissingInput:
                return None
            if ok:
                best = candidate
                lo = candidate + 1000
            else:
                hi = candidate - 1000
        if best is None or best <= 0:
            return None
        achieved = None
        trial = recompute(context, best)
        if "dti.back_ratio" in trial:
            achieved = str(trial["dti.back_ratio"][0])
        return CounterofferHint(rule_id, solve_for,
                                str(best.quantize(Decimal("0.01"))), achieved)


__all__ = ["JsonRulesEngine", "RulesEngine", "Context", "RecomputeFn"]
