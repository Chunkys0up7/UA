# Spec Deviations Register (per 02 §12)

Deviations from the spec discovered during implementation. Each entry names the affected spec section, the deviation, rationale, and impact.

## D-P0-1 — useCoAgent run/start unbound (upstream defect); runs started via bound HttpAgent

- **Spec affected:** `13 §5/§6` (useCoAgent-driven runs), `03 §5`.
- **Found:** Phase 0 gate testing, 2026-07-10.
- **Defect:** `@copilotkit/react-core` 1.57.x–1.62.x `useCoAgent` returns `start: agent.runAgent` and `run: agent.runAgent` as **unbound** method references. Invoking them calls `HttpAgent.runAgent` with `this === undefined` → `TypeError: Cannot set properties of undefined (setting 'abortController')`.
- **Resolution:** agent instances are module-level singletons (`frontend/lib/agents.ts`) registered with `<CopilotKit agents__unsafe_dev_only>`. Pages start/resume runs via the **bound** instance: `underwriterAgent.runAgent({forwardedProps})`; resume uses `forwardedProps.command.resume` with the unchanged `interrupt-resume.schema.json` payload. Interrupts are consumed from the agent's AG-UI event stream (`CUSTOM name="on_interrupt"`); `useLangGraphInterrupt` remains registered as a probe and MAY replace the manual subscription if a fixed upstream release lands. `useCoAgent` remains in use for shared-state subscription (unaffected).
- **Impact:** none on decision semantics, audit, or the resume contract. Phase 6 DecisionGate consumes the same packet/resume shapes.

## D-P0-2 — Dependency drift resolutions (bootstrap verification, 03 §3 / 16 §1)

Resolved at Phase 0 bootstrap (2026-07-10), lockfiles authoritative:

| Package | Spec range | Resolved | Why |
|---|---|---|---|
| langgraph | `>=0.4,<1` (original) | `>=1.0.2,<2` → 1.2.9 | copilotkit≥0.1.88 → ag-ui-langgraph≥0.0.38 → langchain≥1.2 requires langgraph 1.x (03 §3 updated) |
| langgraph-checkpoint-sqlite | `>=2,<3` | `>=3,<4` → 3.1.0 | 2.0.x calls removed `JsonPlusSerializer.dumps` against langgraph 1.2's checkpoint base |
| aiosqlite | (transitive) | `>=0.20,<0.22` → 0.21.0 | 0.22 removed the Thread base class; checkpoint-sqlite calls `Connection.is_alive()` |
| @copilotkit/* (js) | `^1.10.0` | pinned `1.57.1` | `^1.10` resolved 1.62.3 whose provider rewrite (thread manager, proxied agents) is unverified; 1.57.x is the skill-verified line. D-P0-1 applies to both. |

## D-P0-3 — AsyncSqliteSaver constructed in FastAPI lifespan

- **Spec affected:** `09 §6` (checkpointer), `03 §5` (mount wiring).
- **Defect/constraint:** `AsyncSqliteSaver.__init__` requires a running event loop; module-import-time mounting (scaffold default) crashes.
- **Resolution:** `/agent/underwriter` mounts from the FastAPI lifespan (`runtime.mount_underwriter`), before the server accepts requests. Documented in `backend/app/runtime.py`.
- **Impact:** none; routes are registered before first request.
