"""Deterministic mock UALLMClient (specs/10 §5, FR-LLM-4, FR-EXT-4).

extract() returns the document's synthetic ground_truth sidecar verbatim
with confidence 0.99; narrate/draft render deterministic templates. The
entire pipeline runs with no vendor key and full determinism (NFR-1).
"""

from __future__ import annotations

import time

from app.audit.canonical import canonical_json
from app.llm.ua_base import ExtractionResult, Prompt, TextResult, make_record

MOCK_MODEL_ID = "mock-deterministic-v1"


class MockUALLMClient:
    async def extract(self, *, prompt: Prompt, document_text: str,
                      ground_truth: dict | None, call_site: str) -> ExtractionResult:
        started = time.perf_counter()
        fields = dict(ground_truth or {})
        confidence = {k: "0.99" for k in fields}
        output = canonical_json({"fields": fields, "confidence": confidence})
        record = make_record(
            prompt=prompt, model_id=MOCK_MODEL_ID, input_text=document_text,
            output_text=output, started=started, retries=0, call_site=call_site,
        )
        return ExtractionResult(fields=fields, confidence=confidence, record=record)

    async def narrate(self, *, prompt: Prompt, payload: dict,
                      call_site: str) -> TextResult:
        started = time.perf_counter()
        text = f"[mock narrative] {canonical_json(payload)[:200]}"
        record = make_record(
            prompt=prompt, model_id=MOCK_MODEL_ID,
            input_text=canonical_json(payload), output_text=text,
            started=started, retries=0, call_site=call_site,
        )
        return TextResult(text=text, record=record)

    async def draft(self, *, prompt: Prompt, payload: dict,
                    call_site: str) -> TextResult:
        started = time.perf_counter()
        template = prompt.fallback_template or "Provide: {requirement} for {subject}."
        try:
            text = template.format(**payload)
        except (KeyError, IndexError):
            text = f"Provide documentation for {payload.get('source_id', 'the finding')}."
        record = make_record(
            prompt=prompt, model_id=MOCK_MODEL_ID,
            input_text=canonical_json(payload), output_text=text,
            started=started, retries=0, call_site=call_site,
        )
        return TextResult(text=text, record=record)


__all__ = ["MockUALLMClient", "MOCK_MODEL_ID"]
