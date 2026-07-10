"""Assembly + engine over the REAL golden packages (T-DAT-2 core,
T-POL-4 end-to-end): mock-extract every document, assemble the case,
evaluate both packs, assert the specs/14 §4 expected outcomes."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import pathlib

import pytest

from app.adapters import (
    SimCreditBureau, SimEmploymentVerifier, SimFloodZone, SimGeoDistance,
    SimOfacScreen,
)
from app.agent.assembly import assemble_case
from app.llm.ua_base import PromptRegistry
from app.llm.ua_mock import MockUALLMClient
from app.policy_engine import JsonRulesEngine, load_packs
from synthetic.archetypes import GOLDEN_ARCHETYPES, by_name
from synthetic.generate import BASE_DATE

REPO = pathlib.Path(__file__).resolve().parents[2]
PACKS = load_packs(REPO / "policy" / "packs" / "conforming-2026.1.0",
                   REPO / "policy" / "packs" / "state-overlays-2026.1.0")
REGISTRY = PromptRegistry(REPO / "policy" / "prompts")
ENGINE = JsonRulesEngine()

EXTRACTION_PROMPTS = {
    "paystub": "extraction/paystub", "w2": "extraction/w2",
    "tax_return_1040": "extraction/tax-return-1040",
    "schedule_c": "extraction/schedule-c",
    "bank_statement": "extraction/bank-statement",
    "appraisal": "extraction/appraisal", "urla_1003": "extraction/urla-1003",
    "gift_letter": "extraction/gift-letter", "lease": "extraction/lease",
}


def load_golden(name: str) -> dict:
    return json.loads(
        (REPO / "data" / "loans" / f"{name}.json").read_text(encoding="utf-8"))


def run_case(package: dict, application_id: str = "APPASSEMBLY00000000000000"):
    client = MockUALLMClient()

    async def extract_all():
        extractions = {}
        for doc in package["documents"]:
            prompt_id = EXTRACTION_PROMPTS.get(doc["doc_type"])
            if prompt_id is None:  # tri_merge_credit / voe skipped (specs/09 §3.2)
                continue
            result = await client.extract(
                prompt=REGISTRY.get(prompt_id),
                document_text=doc["text_rendering"],
                ground_truth=doc.get("ground_truth"),
                call_site="document_extraction")
            extractions[doc["doc_id"]] = {
                "fields": result.fields, "confidence": result.confidence,
                "prompt": f"{prompt_id}@v{REGISTRY.active[prompt_id]}",
                "model": result.record.model_id}
        return extractions

    extractions = asyncio.run(extract_all())
    adapter_results = {
        "bureau": SimCreditBureau().pull(package=package,
                                         permissible_purpose="credit_transaction"),
        "voe": SimEmploymentVerifier().verify(borrower=package["borrowers"][0]),
        "flood": SimFloodZone().lookup(property_data=package["property"]),
        "ofac": SimOfacScreen().screen(
            parties=[b["full_name"] for b in package["borrowers"]]),
        "geo": SimGeoDistance().distance(
            property_data=package["property"],
            employment=package["borrowers"][0]["employment"][0]),
    }
    case = assemble_case(
        application_id=application_id, package=package, extractions=extractions,
        adapter_results=adapter_results, constants=PACKS.constants,
        states_index=PACKS.states_index,
        reference_indices=PACKS.reference_indices,
        compensating_factors=PACKS.compensating_factors,
        pack_version=PACKS.base_version, as_of=BASE_DATE)
    rules = ENGINE.evaluate(PACKS, case.context)
    return case, rules


@pytest.mark.parametrize("archetype", GOLDEN_ARCHETYPES, ids=lambda a: a.name)
def test_expected_rule_failures(archetype):
    case, rules = run_case(load_golden(archetype.name))
    eligibility_failed = {
        e.rule_id for e in rules.evaluations
        if e.outcome in ("fail", "refer")
    }
    for rule_id in archetype.expected_failed_rules:
        assert rule_id in eligibility_failed, (
            f"{archetype.name}: expected {rule_id} to fail; "
            f"failed={sorted(eligibility_failed)}")
    flags = {f.flag_code for f in case.red_flags}
    for flag in archetype.expected_red_flags:
        assert flag in flags, f"{archetype.name}: expected {flag}; got {sorted(flags)}"


@pytest.mark.parametrize("archetype", GOLDEN_ARCHETYPES, ids=lambda a: a.name)
def test_family_consistency(archetype):
    """decline family <=> ineligible rollup; approve family <=> eligible."""
    _, rules = run_case(load_golden(archetype.name))
    if archetype.expected_family == "decline":
        assert rules.overall == "ineligible", archetype.name
    elif archetype.expected_family == "approve":
        assert rules.overall == "eligible", (
            archetype.name,
            [(e.rule_id, e.outcome) for e in rules.evaluations
             if e.severity == "eligibility" and e.outcome in ("fail", "refer")])


def test_clean_approve_details():
    case, rules = run_case(load_golden("clean-approve"))
    assert rules.overall == "eligible"
    assert case.four_cs["credit"]["representative_score"] == 780  # middle of (774,780,787) = target
    assert len(case.atr) == 8
    assert all(a.basis for a in case.atr)
    # every displayed number resolves in the lineage graph (HR-3)
    for ref_key in ("back_ratio_ref", "qualifying_income_ref"):
        ref = case.four_cs["capacity"][ref_key]
        assert ref in case.lineage.nodes


def test_counteroffer_end_to_end():
    """The 06 §3 vector through the full stack: assembly -> engine -> $429k."""
    from decimal import Decimal
    from app.domain.calculations.dti import principal_interest
    from app.domain.lineage import Lineage
    from app.domain.numeric import D, HUNDRED, money, ratio_pct

    package = load_golden("decline-dti-counteroffer")
    case, _ = run_case(package)
    taxes = D(package["property"]["annual_taxes"]) / 12
    hazard = D(package["property"]["annual_hazard_insurance"]) / 12
    income = D(case.four_cs["capacity"]["qualifying_income_monthly"])
    liabilities = D(case.computed["dti"]["liabilities"])

    def recompute(ctx, amount):
        lin = Lineage(application_id="CO0000000000000000000000000")
        pi = principal_interest(
            lin, loan_amount=lin.add("package_stated", "a", str(money(amount))),
            note_rate_pct=lin.add("package_stated", "r",
                                  package["loan"]["note_rate"]),
            term_months=package["loan"]["term_months"])
        back = ratio_pct((D(pi.value) + taxes + hazard + liabilities)
                         / income * HUNDRED)
        out = dict(ctx)
        out["loan.amount"] = (money(amount), None)
        out["dti.back_ratio"] = (back, None)
        return out

    rules = ENGINE.evaluate(PACKS, case.context, recompute=recompute)
    hint = next(h for h in rules.counteroffer_hints if h.rule_id == "DTI-001")
    assert abs(Decimal(hint.max_value) - Decimal("429000.00")) <= 1000


def test_occupancy_critical_flag():
    case, _ = run_case(load_golden("occupancy-fraud-flag"))
    critical = [f for f in case.red_flags if f.severity == "critical"]
    assert any(f.flag_code == "RF-OCC-INSURANCE" for f in critical)


def test_ofac_marker_detected():
    package = load_golden("clean-approve")
    package["borrowers"][0]["full_name"] = "SANCTIONED TEST PARTY"
    result = SimOfacScreen().screen(
        parties=[b["full_name"] for b in package["borrowers"]])
    assert result.result["hit"]
