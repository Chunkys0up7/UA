"""Anthropic UALLMClient — THE ONLY module importing `anthropic` for the
underwriting pipeline (HR-9, T-LLM-3; swap procedure in specs/10 §6).

[ANTHROPIC-SPECIFIC] Messages API; temperature/max_tokens from the
prompt's model_params; extraction responses must be bare JSON (the
prompt templates instruct this) — a retry re-asks once on parse or
schema failure (FR-EXT-3). Model id comes from LLM_MODEL env verbatim;
never hardcoded at call sites.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.audit.canonical import canonical_json
from app.llm.ua_base import ExtractionResult, Prompt, TextResult, make_record


class AnthropicUALLMClient:
    def __init__(self, *, model_id: str, api_key: str | None = None):
        import anthropic  # lazy vendor import (HR-9)

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model_id = model_id

    async def _complete(self, prompt: Prompt, rendered: str) -> str:
        params = prompt.model_params or {}
        message = await self._client.messages.create(
            model=self.model_id,
            max_tokens=int(params.get("max_tokens", 1024)),
            temperature=float(params.get("temperature", 0)),
            messages=[{"role": "user", "content": rendered}],
        )
        return "".join(
            block.text for block in message.content if block.type == "text"
        )

    async def extract(self, *, prompt: Prompt, document_text: str,
                      ground_truth: dict | None, call_site: str) -> ExtractionResult:
        started = time.perf_counter()
        rendered = prompt.template.replace("{{document_text}}", document_text)
        retries = 0
        last_error: Exception | None = None
        for attempt in range(2):  # one retry on invalid output (FR-EXT-3)
            retries = attempt
            raw = await self._complete(prompt, rendered)
            try:
                parsed: dict[str, Any] = json.loads(raw)
                confidence = parsed.pop("confidence", {})
                record = make_record(
                    prompt=prompt, model_id=self.model_id, input_text=rendered,
                    output_text=raw, started=started, retries=retries,
                    call_site=call_site,
                )
                return ExtractionResult(fields=parsed, confidence=confidence,
                                        record=record)
            except json.JSONDecodeError as err:
                last_error = err
        raise ExtractionFailed(prompt.id, str(last_error), retries)

    async def narrate(self, *, prompt: Prompt, payload: dict,
                      call_site: str) -> TextResult:
        started = time.perf_counter()
        rendered = prompt.template.replace("{{four_cs_json}}", canonical_json(payload))
        raw = await self._complete(prompt, rendered)
        try:
            text = json.loads(raw).get("narrative", raw)
        except json.JSONDecodeError:
            text = raw
        record = make_record(prompt=prompt, model_id=self.model_id,
                             input_text=rendered, output_text=raw,
                             started=started, retries=0, call_site=call_site)
        return TextResult(text=text, record=record)

    async def draft(self, *, prompt: Prompt, payload: dict,
                    call_site: str) -> TextResult:
        started = time.perf_counter()
        rendered = prompt.template.replace("{{finding_json}}", canonical_json(payload))
        raw = await self._complete(prompt, rendered)
        try:
            text = json.loads(raw).get("text", raw)
        except json.JSONDecodeError:
            text = raw
        record = make_record(prompt=prompt, model_id=self.model_id,
                             input_text=rendered, output_text=raw,
                             started=started, retries=0, call_site=call_site)
        return TextResult(text=text, record=record)


class ExtractionFailed(Exception):
    def __init__(self, prompt_id: str, detail: str, retries: int):
        self.prompt_id, self.retries = prompt_id, retries
        super().__init__(f"{prompt_id}: extraction failed after {retries + 1} attempts: {detail}")


__all__ = ["AnthropicUALLMClient", "ExtractionFailed"]
