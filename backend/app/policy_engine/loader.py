"""Pack loading with integrity + validation gates (specs/07 §5, 17 §3,
FR-POL-2/-4, FR-STA-2/-4, T-POL-2/-3, T-SOV-2).

Load-time failures are LOUD: a tampered file, an unbound reason code, an
uncited overlay rule, or an undocumented input path all abort the load.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.policy_engine.result import LoadedPacks

# Documented evaluation-context vocabulary (specs/07 §3 + specs/17 §4).
VOCABULARY: frozenset[str] = frozenset({
    "loan.amount", "loan.purpose", "loan.occupancy", "loan.units",
    "loan.county_high_cost", "loan.is_cash_out",
    "loan.apr", "loan.points_and_fees_pct", "loan.lender_fees_pct",
    "ltv.ltv", "ltv.cltv",
    "dti.front_ratio", "dti.back_ratio",
    "income.qualifying_monthly", "income.residual_monthly",
    "income.variable_included_under_12mo", "income.discrepancies_exceeded",
    "income.se_history_months",
    "credit.representative_score", "credit.open_disputes",
    "credit.bk7_months_since", "credit.fc_months_since",
    "credit.late_mortgage_12mo", "credit.report_age_days",
    "assets.reserves_months", "assets.unsourced_large_deposits",
    "assets.unseasoned_funds", "assets.gift_funds_undocumented",
    "compensating.count",
    "property.type", "property.state", "property.homestead",
    "appraisal.age_days",
    "state.flags.community_property", "state.flags.wet_funding",
    "state.flags.attorney_closing", "state.flags.disparate_impact_monitoring",
    "state.apr_spread_treasury", "state.rate_spread_pmms", "apor.spread",
    "state.subordinate_lien_count", "state.prior_a6_days",
    "state.tx_notice_on_file",
    "borrowers.non_borrowing_spouse_present",
})

_BASE_RULE_FILES = (
    "loan-limits.rules.json", "ltv-matrix.rules.json", "dti.rules.json",
    "credit.rules.json", "income.rules.json", "assets.rules.json",
    "property.rules.json",
)


class PolicyPackIntegrityError(Exception):
    """Manifest sha256 mismatch — the pack has been altered (HR-7)."""


class PolicyPackValidationError(Exception):
    """Pack content violates load-time invariants (FR-POL-4, FR-STA-2)."""


def _verify_manifest(pack_dir: Path) -> str:
    """Verify every file hash in pack.json; return the manifest-root hash."""
    pack = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    for name, expected in pack["files"].items():
        actual = hashlib.sha256((pack_dir / name).read_bytes()).hexdigest()
        if actual != expected:
            raise PolicyPackIntegrityError(
                f"{pack_dir.name}/{name}: sha256 {actual} != manifest {expected}"
            )
    manifest_root = hashlib.sha256(
        json.dumps(pack["files"], sort_keys=True).encode()
    ).hexdigest()
    return manifest_root


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_rules_file(
    parsed: dict, reason_codes: dict[str, dict], *, overlay: bool, filename: str
) -> None:
    for rule in parsed.get("rules", []):
        rid = rule.get("id", "<missing id>")
        code = rule.get("on_fail", {}).get("reason_code")
        if not code or code not in reason_codes:
            raise PolicyPackValidationError(
                f"{filename}:{rid}: on_fail.reason_code {code!r} not bound (FR-POL-4)"
            )
        if overlay and not rule.get("citation"):
            raise PolicyPackValidationError(
                f"{filename}:{rid}: overlay rule missing citation (FR-STA-2)"
            )
        for path in rule.get("inputs", []):
            if path not in VOCABULARY:
                raise PolicyPackValidationError(
                    f"{filename}:{rid}: input {path!r} not in documented vocabulary (T-POL-3)"
                )


def load_packs(base_dir: Path, overlay_dir: Path) -> LoadedPacks:
    base_manifest = _verify_manifest(base_dir)
    overlay_manifest = _verify_manifest(overlay_dir)

    base_pack = _load_json(base_dir / "pack.json")
    overlay_pack = _load_json(overlay_dir / "pack.json")

    # Merge reason codes; namespaces must be disjoint (specs/17 §3).
    base_codes = _load_json(base_dir / "reason-codes.json")["codes"]
    state_codes = _load_json(overlay_dir / "reason-codes.state.json")["codes"]
    collision = set(base_codes) & set(state_codes)
    if collision:
        raise PolicyPackValidationError(f"reason-code collision: {sorted(collision)}")
    reason_codes = {**base_codes, **state_codes}

    rules_files = []
    for name in _BASE_RULE_FILES:
        parsed = _load_json(base_dir / name)
        _validate_rules_file(parsed, reason_codes, overlay=False, filename=name)
        rules_files.append(parsed)

    states_index = _load_json(overlay_dir / "states-index.json")
    overlay_common = _load_json(overlay_dir / "common.rules.json")
    _validate_rules_file(overlay_common, reason_codes, overlay=True,
                         filename="common.rules.json")
    overlay_by_state: dict[str, dict] = {}
    for state, filename in states_index["rule_files"].items():
        parsed = _load_json(overlay_dir / filename)
        _validate_rules_file(parsed, reason_codes, overlay=True, filename=filename)
        overlay_by_state[state] = parsed

    return LoadedPacks(
        base_version=f"{base_pack['pack_id']}-{base_pack['version']}",
        base_manifest_sha256=base_manifest,
        overlay_version=f"{overlay_pack['pack_id']}-{overlay_pack['version']}",
        overlay_manifest_sha256=overlay_manifest,
        rules_files=rules_files,
        overlay_common=overlay_common,
        overlay_by_state=overlay_by_state,
        reason_codes=reason_codes,
        compensating_factors=_load_json(base_dir / "compensating-factors.json")["factors"],
        constants=_load_json(base_dir / "constants.json"),
        states_index=states_index,
        reference_indices=_load_json(overlay_dir / "reference-indices.json"),
        vocabulary=VOCABULARY,
    )


__all__ = [
    "load_packs", "VOCABULARY",
    "PolicyPackIntegrityError", "PolicyPackValidationError",
]
