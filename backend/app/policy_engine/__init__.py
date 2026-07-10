"""Deterministic policy engine (specs/07, specs/17). The ONLY component
that produces eligibility outcomes (HR-1)."""

from .engine import JsonRulesEngine, RulesEngine
from .loader import PolicyPackIntegrityError, PolicyPackValidationError, load_packs
from .result import (
    Artifact,
    CounterofferHint,
    LoadedPacks,
    RuleEvaluation,
    RulesResult,
)

__all__ = [
    "JsonRulesEngine", "RulesEngine", "load_packs", "LoadedPacks",
    "PolicyPackIntegrityError", "PolicyPackValidationError",
    "RuleEvaluation", "RulesResult", "CounterofferHint", "Artifact",
]
