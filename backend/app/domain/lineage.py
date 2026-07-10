"""Lineage model (specs/04 §3, HR-3).

Every computed value is a `TracedValue{value, lineage_ref}`. Refs are
CONTENT-ADDRESSED: sha256 over (application_id, kind, label, value,
parents, method), so identical inputs always yield identical refs.
This keeps `domain/` free of randomness (T-CAL-8) and makes snapshot
replay reproduce the exact same lineage graph (T-REP-1).

Calculations append `LineageNode`s to a `Lineage` accumulator supplied
by the caller; the accumulator is the only "output channel" besides
return values, so functions stay deterministic and side-effect free.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

LineageKind = Literal[
    "extracted_field",
    "package_stated",
    "calculation",
    "rule_input",
    "adapter_result",
    "constant_policy",
]


@dataclass(frozen=True)
class TracedValue:
    value: str  # canonical Decimal string (or scalar as string)
    lineage_ref: str

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.value


@dataclass(frozen=True)
class LineageNode:
    ref: str
    application_id: str
    kind: LineageKind
    label: str
    value: str
    method: str | None
    parents: tuple[str, ...]
    source_id: str | None
    meta: tuple[tuple[str, str], ...]  # sorted key/value pairs (hashable)


def _content_ref(
    application_id: str,
    kind: str,
    label: str,
    value: str,
    parents: tuple[str, ...],
    method: str | None,
) -> str:
    payload = "\x1f".join(
        [application_id, kind, label, value, ",".join(parents), method or ""]
    )
    return "L" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:25]


@dataclass
class Lineage:
    """Per-run lineage accumulator (deduplicating; deterministic order)."""

    application_id: str
    nodes: dict[str, LineageNode] = field(default_factory=dict)

    def add(
        self,
        kind: LineageKind,
        label: str,
        value: str,
        *,
        parents: tuple[str, ...] = (),
        method: str | None = None,
        source_id: str | None = None,
        meta: dict[str, str] | None = None,
    ) -> TracedValue:
        ref = _content_ref(self.application_id, kind, label, value, parents, method)
        if ref not in self.nodes:
            self.nodes[ref] = LineageNode(
                ref=ref,
                application_id=self.application_id,
                kind=kind,
                label=label,
                value=value,
                method=method,
                parents=parents,
                source_id=source_id,
                meta=tuple(sorted((meta or {}).items())),
            )
        return TracedValue(value=value, lineage_ref=ref)

    def constant(self, label: str, value: str, pack_version: str) -> TracedValue:
        """A policy constant with pack-version citation (specs/06 §1)."""
        return self.add(
            "constant_policy",
            label,
            value,
            method="pack_constant",
            meta={"pack_version": pack_version},
        )


__all__ = ["TracedValue", "LineageNode", "Lineage", "LineageKind"]
