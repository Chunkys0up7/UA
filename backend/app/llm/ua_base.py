"""UA LLMClient protocol + prompt registry (specs/10 §2/§5, HR-9).

This is the UA-specific LLM boundary (the scaffold's chat LLMProvider in
llm/base.py serves the demo chat agent; underwriting uses THIS).
Exactly one module imports the vendor SDK: ua_anthropic.py (T-LLM-3).

Every call produces a CallRecord that feeds the llm_call audit event
(FR-LLM-2). Prompt ids are validated against policy/prompts/registry.json
at call time — an unregistered prompt id is a defect (FR-LLM-3).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from app.audit.canonical import canonical_json, sha256_hex


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    template: str
    model_params: dict[str, Any]
    output_schema: dict[str, Any] | None
    fallback_template: str | None = None


class UnregisteredPromptError(Exception):
    """Prompt id not in policy/prompts/registry.json (FR-LLM-3)."""


class PromptRegistry:
    """Loads the versioned prompt set pinned for a run (HR-7)."""

    def __init__(self, prompts_dir: Path):
        self._dir = Path(prompts_dir)
        registry = json.loads(
            (self._dir / "registry.json").read_text(encoding="utf-8"))
        self.active: dict[str, int] = registry["active"]
        self._cache: dict[str, Prompt] = {}

    def get(self, prompt_id: str) -> Prompt:
        if prompt_id not in self.active:
            raise UnregisteredPromptError(prompt_id)
        if prompt_id not in self._cache:
            version = self.active[prompt_id]
            group, name = prompt_id.split("/", 1)
            raw = yaml.safe_load(
                (self._dir / group / f"{name}.v{version}.yaml")
                .read_text(encoding="utf-8"))
            self._cache[prompt_id] = Prompt(
                id=raw["id"], version=raw["version"], template=raw["template"],
                model_params=raw.get("model_params") or {},
                output_schema=raw.get("output_schema"),
                fallback_template=raw.get("fallback_template"),
            )
        return self._cache[prompt_id]

    def pinned_versions(self) -> dict[str, int]:
        return dict(self.active)


@dataclass(frozen=True)
class CallRecord:
    """Feeds the llm_call audit event (specs/10 §4)."""

    prompt_id: str
    prompt_version: int
    model_id: str
    params: dict[str, Any]
    input_sha256: str
    output_sha256: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    retries: int
    call_site: str

    def audit_payload(self) -> dict[str, Any]:
        return {
            "prompt_id": self.prompt_id, "prompt_version": self.prompt_version,
            "model_id": self.model_id, "params": self.params,
            "input_sha256": self.input_sha256, "output_sha256": self.output_sha256,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms, "retries": self.retries,
            "call_site": self.call_site,
        }


@dataclass(frozen=True)
class ExtractionResult:
    fields: dict[str, Any]         # schema-conformant extracted fields
    confidence: dict[str, Any]     # 0..1 per field
    record: CallRecord


@dataclass(frozen=True)
class TextResult:
    text: str
    record: CallRecord


class UALLMClient(Protocol):
    """specs/10 §2 — extraction, narrative, drafting. Chat lands in P5."""

    async def extract(self, *, prompt: Prompt, document_text: str,
                      ground_truth: dict | None, call_site: str) -> ExtractionResult: ...

    async def narrate(self, *, prompt: Prompt, payload: dict,
                      call_site: str) -> TextResult: ...

    async def draft(self, *, prompt: Prompt, payload: dict,
                    call_site: str) -> TextResult: ...


def make_record(
    *, prompt: Prompt, model_id: str, input_text: str, output_text: str,
    started: float, retries: int, call_site: str,
) -> CallRecord:
    return CallRecord(
        prompt_id=prompt.id, prompt_version=prompt.version, model_id=model_id,
        params=prompt.model_params,
        input_sha256=sha256_hex(input_text),
        output_sha256=sha256_hex(output_text),
        input_tokens=max(1, len(input_text) // 4),
        output_tokens=max(1, len(output_text) // 4),
        latency_ms=int((time.perf_counter() - started) * 1000),
        retries=retries, call_site=call_site,
    )


__all__ = [
    "Prompt", "PromptRegistry", "UnregisteredPromptError", "CallRecord",
    "ExtractionResult", "TextResult", "UALLMClient", "make_record",
]
