# UA — Underwriting Agent

An AI-assisted **mortgage underwriting workbench** reference implementation for a large US national bank: a deterministic LangGraph underwriting pipeline with a human decision gate, a CopilotKit visual workbench with click-through lineage on every number, and a tamper-evident, replayable audit trail.

**Synthetic data only. Not a production system.** It implements the *controls* a production system needs (ECOA/Reg B adverse action, ATR/QM 8 factors, HMDA capture, fair-lending isolation, GSE AI-governance patterns, hash-chained audit + byte-exact replay) so the architecture transfers onto a bank's internal network.

## Start here

**[`specs/00-overview.md`](specs/00-overview.md)** — the complete, self-contained specification package (17 documents + machine-readable policy pack, prompts, and JSON Schemas). The specs are the source of truth; an implementing agent can rebuild this entire system from `specs/` alone.

Key entry points:

| | |
|---|---|
| Hard rules & scope | [specs/00-overview.md](specs/00-overview.md) |
| Requirements (FR/NFR IDs) | [specs/01-requirements.md](specs/01-requirements.md) |
| Compliance matrix | [specs/02-compliance-matrix.md](specs/02-compliance-matrix.md) |
| LLM transparency & provider swap | [specs/10-llm-usage-register.md](specs/10-llm-usage-register.md) |
| Audit & repeatability | [specs/11-audit-repeatability.md](specs/11-audit-repeatability.md) |
| Build order & gates | [specs/16-implementation-plan.md](specs/16-implementation-plan.md) |

## Status

- [x] Specification package (specs/) — complete, cold-start reviewed
- [ ] Phase 0 — walking skeleton (CopilotKit ⇄ LangGraph interrupt round-trip)
- [ ] Phases 1–7 — implementation per [specs/16-implementation-plan.md](specs/16-implementation-plan.md)
