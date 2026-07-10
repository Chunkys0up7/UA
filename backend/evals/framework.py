"""
Eval framework — scenario-driven LLM/action testing.

Scenario shape (YAML):

    name: weather_lookup
    description: Asks the assistant for weather and expects a tool call.
    provider: mock           # optional, default = current LLM_PROVIDER
    messages:
      - role: user
        content: "/tool get_weather {\"city\": \"London\"}"
    expect:
      tool_calls:
        - name: get_weather
          arguments_contains:
            city: London
      content_contains: []   # optional substrings expected in response
      content_matches: null  # optional regex

The framework loads every `*.yaml` from `evals/scenarios/`, runs each
through the configured provider, and reports pass/fail.

Spec: docs/classes/EvalRunner.md

Complexity:
    run_one:  O(scenario.messages * provider.cost) — usually 1 LLM call
    run_all:  O(N) over scenarios, sequential by default
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import Settings, get_settings
from app.llm import LLMMessage, LLMProvider, get_provider
from app.llm.base import LLMResponse


@dataclass(frozen=True, slots=True)
class EvalExpectation:
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    content_contains: list[str] = field(default_factory=list)
    content_matches: str | None = None


@dataclass(frozen=True, slots=True)
class EvalCase:
    name: str
    description: str
    messages: list[LLMMessage]
    expect: EvalExpectation
    provider_override: str | None = None


@dataclass(frozen=True, slots=True)
class EvalResult:
    case: EvalCase
    passed: bool
    failures: tuple[str, ...]
    response: LLMResponse

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True, slots=True)
class EvalReport:
    results: tuple[EvalResult, ...]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    def render(self) -> str:
        lines = [f"Eval report: {self.passed}/{self.total} passed"]
        for r in self.results:
            lines.append(f"  [{r.status}] {r.case.name} — {r.case.description}")
            for f in r.failures:
                lines.append(f"      ! {f}")
        return "\n".join(lines)


# ---------- loading ----------------------------------------------------------


def _parse_case(raw: dict[str, Any]) -> EvalCase:
    msgs = [
        LLMMessage(role=m["role"], content=m["content"])
        for m in raw.get("messages", [])
    ]
    expect_raw = raw.get("expect", {}) or {}
    expect = EvalExpectation(
        tool_calls=list(expect_raw.get("tool_calls", []) or []),
        content_contains=list(expect_raw.get("content_contains", []) or []),
        content_matches=expect_raw.get("content_matches"),
    )
    return EvalCase(
        name=raw["name"],
        description=raw.get("description", ""),
        messages=msgs,
        expect=expect,
        provider_override=raw.get("provider"),
    )


def load_scenarios(directory: Path) -> list[EvalCase]:
    """Load every `*.yaml` in `directory` (non-recursive)."""
    cases: list[EvalCase] = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        cases.append(_parse_case(raw))
    return cases


# ---------- runner -----------------------------------------------------------


class EvalRunner:
    """Runs `EvalCase`s through an `LLMProvider` and checks expectations."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._default_provider = provider or get_provider()
        self._settings = get_settings()

    def _resolve_provider(self, override: str | None) -> LLMProvider:
        if not override or override == self._settings.llm_provider:
            return self._default_provider
        # Build a one-off provider when a scenario forces a specific one.
        cfg = self._settings.model_copy(update={"llm_provider": override})
        return get_provider(cfg)

    async def run_one(self, case: EvalCase) -> EvalResult:
        provider = self._resolve_provider(case.provider_override)
        rsp = await provider.generate(case.messages)
        failures = list(self._check(case.expect, rsp))
        return EvalResult(
            case=case,
            passed=not failures,
            failures=tuple(failures),
            response=rsp,
        )

    async def run_all(self, cases: Iterable[EvalCase]) -> EvalReport:
        results: list[EvalResult] = []
        for c in cases:
            results.append(await self.run_one(c))
        return EvalReport(results=tuple(results))

    # --- assertions -------------------------------------------------------
    @staticmethod
    def _check(expect: EvalExpectation, rsp: LLMResponse) -> Iterable[str]:
        for substr in expect.content_contains:
            if substr not in rsp.content:
                yield f"content missing substring {substr!r}"
        if expect.content_matches is not None and not re.search(
            expect.content_matches, rsp.content
        ):
            yield f"content did not match regex {expect.content_matches!r}"
        for expected in expect.tool_calls:
            if not _matches_any_tool(expected, rsp.tool_calls):
                yield f"expected tool call {expected!r} not found"


def _matches_any_tool(expected: dict[str, Any], actuals: tuple[Any, ...]) -> bool:
    for tc in actuals:
        if expected.get("name") and expected["name"] != tc.name:
            continue
        contains = expected.get("arguments_contains") or {}
        if all(tc.arguments.get(k) == v for k, v in contains.items()):
            return True
    return False
