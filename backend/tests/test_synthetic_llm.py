"""T-DAT-1/2 (generator determinism + archetype fidelity), T-EXT-3,
T-LLM-1/3 (register + import isolation), T-ADP-1 (adapter payloads)."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import pathlib
import random
from decimal import Decimal

import pytest
from jsonschema import Draft202012Validator

from app.adapters import (
    SimCreditBureau, SimEmploymentVerifier, SimFloodZone, SimGeoDistance,
    SimOfacScreen,
)
from app.domain.numeric import D, HUNDRED, ratio_pct
from app.llm.ua_base import PromptRegistry, UnregisteredPromptError
from app.llm.ua_mock import MockUALLMClient
from synthetic.archetypes import GOLDEN_ARCHETYPES, by_name
from synthetic.generate import build_package, generate_archetypes

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (REPO / "specs" / "schemas" / "loan-package.schema.json").read_text(encoding="utf-8"))
PROMPTS_DIR = REPO / "policy" / "prompts"
GOLDEN_DIR = REPO / "data" / "loans"

VALIDATOR = Draft202012Validator(SCHEMA)


def load_golden(name: str) -> dict:
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- T-DAT-1
class TestDeterminism:
    def test_same_seed_byte_identical(self, tmp_path):
        a_dir, b_dir = tmp_path / "a", tmp_path / "b"
        generate_archetypes(a_dir, seed=42)
        generate_archetypes(b_dir, seed=42)
        for path in sorted(a_dir.glob("*.json")):
            a = path.read_bytes()
            b = (b_dir / path.name).read_bytes()
            assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest(), path.name

    def test_committed_goldens_match_seed_42(self, tmp_path):
        """data/loans/ must be exactly what seed 42 produces (drift check)."""
        fresh = tmp_path / "fresh"
        generate_archetypes(fresh, seed=42)
        for path in sorted(fresh.glob("*.json")):
            committed = GOLDEN_DIR / path.name
            assert committed.exists(), f"golden missing: {path.name}"
            assert committed.read_bytes() == path.read_bytes(), f"drift: {path.name}"


# ------------------------------------------------------------- T-DAT-2
class TestArchetypeFidelity:
    @pytest.mark.parametrize("archetype", GOLDEN_ARCHETYPES, ids=lambda a: a.name)
    def test_schema_valid(self, archetype):
        errors = sorted(VALIDATOR.iter_errors(load_golden(archetype.name)),
                        key=str)
        assert not errors, [e.message for e in errors[:3]]

    @pytest.mark.parametrize("archetype", GOLDEN_ARCHETYPES, ids=lambda a: a.name)
    def test_back_dti_target_hit(self, archetype):
        """Recompute back DTI from the package's own numbers — the solver
        must have landed within 0.06pp of the archetype target (rounding
        of taxes/hazard/liability split accounts for the tolerance)."""
        package = load_golden(archetype.name)
        income = D(package["processor_computed"]["qualifying_income_monthly"])
        liabilities = D(package["liabilities_stated_monthly_total"])
        loan = D(package["loan"]["amount"])
        from synthetic.generate import _pi_amount
        pi = _pi_amount(str(loan), package["loan"]["note_rate"],
                        package["loan"]["term_months"])
        taxes = D(package["property"]["annual_taxes"]) / 12
        hazard = D(package["property"]["annual_hazard_insurance"]) / 12
        appraised = D(package["property"]["appraised_value"])
        basis = min(appraised, D(package["property"].get("purchase_price") or appraised))
        ltv = (loan / basis * HUNDRED)
        mi = loan * D("0.0055") / 12 if ltv > D("80.005") else D("0")
        back = ratio_pct((pi + taxes + hazard + mi + liabilities) / income * HUNDRED)
        assert abs(back - D(archetype.target_back_dti)) <= D("0.060"), (
            f"{archetype.name}: back {back} vs target {archetype.target_back_dti}")

    def test_counteroffer_archetype_uses_specs06_vector(self):
        package = load_golden("decline-dti-counteroffer")
        assert package["loan"]["amount"] == "640000.00"
        assert package["processor_computed"]["qualifying_income_monthly"] == "11195.83"

    def test_tx_seasoning_package_carries_prior_a6(self):
        package = load_golden("tx-a6-seasoning-decline")
        assert package["property"]["prior_home_equity_loan_date"] == "2025-08-14"  # 320d before 2026-06-30
        assert package["property"]["tx_a6_notice_date"]  # notice on file

    def test_ssns_are_synthetic_range(self):
        for archetype in GOLDEN_ARCHETYPES:
            for borrower in load_golden(archetype.name)["borrowers"]:
                assert borrower["ssn"].startswith("900-"), archetype.name

    def test_large_deposit_present_where_expected(self):
        package = load_golden("large-deposit-flag")
        deposits = [
            d for doc in package["documents"] if doc["doc_type"] == "bank_statement"
            for d in doc["ground_truth"]["deposits"]
            if d["description"] == "TRANSFER IN"
        ]
        assert any(d["amount"] == "14000.00" for d in deposits)
        assert sum(1 for d in deposits if d["amount"] == "2500.00") == 2  # round pattern

    def test_occupancy_flag_package_features(self):
        package = load_golden("occupancy-fraud-flag")
        assert package["property"]["hazard_policy_type"] == "landlord_rental"
        employment = package["borrowers"][0]["employment"][0]
        assert employment["distance_to_property_miles_sidecar"] == 420


# ------------------------------------------------------------- T-EXT-3 / mock LLM
class TestMockLLM:
    def test_extract_returns_ground_truth_deterministically(self):
        registry = PromptRegistry(PROMPTS_DIR)
        prompt = registry.get("extraction/paystub")
        package = load_golden("clean-approve")
        paystub = next(d for d in package["documents"] if d["doc_type"] == "paystub")
        client = MockUALLMClient()

        async def run():
            return await client.extract(
                prompt=prompt, document_text=paystub["text_rendering"],
                ground_truth=paystub["ground_truth"], call_site="test")

        r1, r2 = asyncio.run(run()), asyncio.run(run())
        assert r1.fields == paystub["ground_truth"] == r2.fields
        assert r1.record.output_sha256 == r2.record.output_sha256
        assert r1.record.prompt_id == "extraction/paystub"
        assert r1.record.model_id == "mock-deterministic-v1"

    def test_unregistered_prompt_rejected(self):  # FR-LLM-3
        registry = PromptRegistry(PROMPTS_DIR)
        with pytest.raises(UnregisteredPromptError):
            registry.get("extraction/not-a-real-prompt")

    def test_registry_covers_all_12_register_rows(self):
        registry = PromptRegistry(PROMPTS_DIR)
        assert len(registry.pinned_versions()) == 12
        for prompt_id in registry.pinned_versions():
            assert registry.get(prompt_id).template  # loads + parses


# ------------------------------------------------------------- T-LLM-1/3
class TestLLMGovernance:
    APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"

    def _imports(self, path: pathlib.Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_anthropic_imported_only_by_designated_clients(self):  # T-LLM-3
        # ua_anthropic.py = the underwriting boundary (HR-9);
        # anthropic_provider.py = the scaffold's demo-chat adapter (lazy import,
        # same one-file discipline; removed with the demo agent in P7).
        allowed = {"ua_anthropic.py", "anthropic_provider.py"}
        offenders = []
        for py in self.APP_DIR.rglob("*.py"):
            if "anthropic" in self._imports(py) and py.name not in allowed:
                offenders.append(str(py))
        assert offenders == [], offenders

    def test_no_llm_in_decision_layers(self):  # T-LLM-1 / HR-1
        forbidden_pkgs = ("policy_engine", "aus", "domain", "audit")
        offenders = []
        for pkg in forbidden_pkgs:
            pkg_dir = self.APP_DIR / pkg
            if not pkg_dir.exists():
                continue
            for py in pkg_dir.rglob("*.py"):
                imports = self._imports(py)
                if imports & {"anthropic", "openai"} or any(
                        "llm" in i for i in imports):
                    offenders.append(str(py))
        assert offenders == [], offenders


# ------------------------------------------------------------- T-ADP-1
class TestAdapters:
    def test_all_adapters_emit_versioned_results(self):
        package = load_golden("clean-approve")
        results = [
            SimCreditBureau().pull(package=package,
                                   permissible_purpose="credit_transaction"),
            SimEmploymentVerifier().verify(borrower=package["borrowers"][0]),
            SimFloodZone().lookup(property_data=package["property"]),
            SimOfacScreen().screen(parties=[package["borrowers"][0]["full_name"]]),
            SimGeoDistance().distance(
                property_data=package["property"],
                employment=package["borrowers"][0]["employment"][0]),
        ]
        for result in results:
            payload = result.audit_payload({"application_id": "APPX"})
            assert payload["adapter_name"] and payload["adapter_version"]
        assert results[0].result["permissible_purpose"] == "credit_transaction"

    def test_ofac_marker_hits(self):
        result = SimOfacScreen().screen(parties=["SANCTIONED TEST PARTY"])
        assert result.result["hit"] is True

    def test_geo_reads_sidecar(self):
        package = load_golden("occupancy-fraud-flag")
        result = SimGeoDistance().distance(
            property_data=package["property"],
            employment=package["borrowers"][0]["employment"][0])
        assert result.result["miles"] == 420
