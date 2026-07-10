# 13 — Frontend Workbench (Next.js + CopilotKit)

Requirements covered: FR-UI-1..5, FR-LIN-2, FR-DEC-1..2. Stack per `03 §3`; wiring per `03 §5`. Design language: dense, professional, financial-grade (dark-on-light, tabular numerals, generous drill-down affordances). All numbers displayed from TracedValues are interactive (FR-LIN-2).

---

## 1. Routes

| Route | Screen |
|---|---|
| `/pipeline` | underwriting queue |
| `/loans/[id]` | loan deep-dive workbench (tabbed) |
| `/api/copilotkit` | CopilotRuntime route (not a screen) |

`/` redirects to `/pipeline`.

## 2. Providers & shared state

`components/CopilotProvider.tsx` wraps the app: `<CopilotKit runtimeUrl="/api/copilotkit" agent="underwriter" agents__unsafe_dev_only={{underwriter: memoizedHttpAgent}}>`. `frontend/lib/agent-state.ts` mirrors `schemas/agent-state.schema.json` as TypeScript types — it is the shared-state contract and MUST be kept in sync (T-STA-1 checks the Python and TS shapes against the schema).

```tsx
const { state } = useCoAgent<UnderwritingState>({ name: "underwriter" });
```

## 3. `/pipeline` — queue

`PipelineTable.tsx`: REST `GET /loans`. Columns: borrower, amount, purpose/occupancy, status chip, suggested action (when ready), received date, **⏸ interrupted badge** for runs paused at the gate (resume takes you to the deep-dive). Row click → `/loans/[id]`. A "Submit sample package" action posts a chosen archetype from `data/loans/` (dev convenience).

## 4. `/loans/[id]` — deep-dive

Layout: header (borrower, loan summary, status chip, MLO NMLS id, pack version) + tab strip + right-hand `CopilotSidebar`. Data: `GET /loans/{id}` + live agent state.

Tabs & components:

| Tab | Component(s) | Content |
|---|---|---|
| Overview | `AppSummaryCard`, `AgentProgress`, `NarrativeCard` | loan/property/borrowers; live pipeline stepper (§5); LLM narrative card marked "AI-generated summary — display only" |
| 4 Cs | `FourCsPanel` ×4 (`Credit`,`Capacity`,`Capital`,`Collateral`) | every metric a `<TracedNumber>`; Capacity shows PITIA breakdown + income component table (type, method, monthly, included/excluded); Credit shows rep-score derivation + derogs; Capital shows reserves + large-deposit table; Collateral shows LTV/CLTV + appraisal facts |
| ATR | `AtrChecklist` | the 8 factors, each with basis + evidence link (T-CAL-7 visible proof) |
| Rules & AUS | `RulesTable`, `AusFindingsCard` | every rule evaluation (id, description, outcome chip, inputs w/ TracedNumbers, reason code); AUS recommendation + factor breakdown + messages grouped PTA/PTD/PTF |
| Conditions | `ConditionsBoard` | grouped PTA/PTD/PTF; source badge (rule/AUS/discrepancy/red-flag); LLM-drafted marker; edit/waive at gate time only |
| Red flags | `RedFlagsPanel` | severity-sorted, evidence links |
| Decision | `DecisionGate` (§6) or `DecisionSummary` + `AdverseActionPreview` after finalization | |
| Audit | `AuditTimeline` (§7) | |

### `<TracedNumber>` + `LineagePopover` (FR-LIN-2)
Renders `value` with underline-on-hover; click → popover fetching `GET /lineage/{ref}`: a vertical chain — calculation node (label, method) → operand nodes → extracted-field leaves showing *document, field, value, confidence, prompt@version, model*. Every level expandable; "open document" shows the text rendering with the field's context highlighted (string match). This is the workbench's signature interaction: **DTI 43.2% → click → see the paystub line it came from.**

## 5. Live agent rendering (FR-UI-2)

```tsx
useCoAgentStateRender<UnderwritingState>({
  name: "underwriter",
  render: ({ state }) => <StageStepper stages={state.progress} />,
});
```
`StageStepper`: the 13 pipeline stages enumerated in `schemas/agent-state.schema.json` (`package_validate` … `finalize`; the gate/adverse-action/seal nodes are not display stages), status icons (pending ○ / running ◐ spinner / done ● / warning ⚠ / error ✕), one-line `detail` under the active stage. Also rendered inline in chat while a run streams. 4 Cs tab values update live from `state.four_cs` during the run, then settle on REST data after completion (REST is authoritative; state is a preview).

## 6. `DecisionGate` (FR-UI-3, FR-DEC-1..2)

```tsx
useLangGraphInterrupt({
  render: ({ event, resolve }) => (
    <DecisionForm packet={event.value as DecisionPacket}
                  onSubmit={(resume) => resolve(JSON.stringify(resume))} />
  ),
});
```
`DecisionForm` sections:
1. **Suggested action** banner (with "why": failed rules / critical flags / rollup) — visibly *suggested*, never pre-submitted.
2. **Action picker**: approve-with-conditions / suspend / decline / counteroffer.
3. Decline → **reason-code picker**: checkboxes rendered ONLY from `packet.eligible_reason_codes` (mapped to descriptions), min 1 max 4 (FR-DEC-2). No free-text reasons exist.
4. Counteroffer → terms form seeded from `packet.counteroffer_hints` (e.g., "max amount passing DTI: $429,000").
5. Override (action ≠ suggested) → justification textarea (≥ 20 chars, enforced client + server).
6. Four-eyes (packet.four_eyes_required or decline) → second-reviewer id field (≠ underwriter id).
7. Conditions review list (inline edit/waive → `condition_edits`).
8. Submit → resume payload per `schemas/interrupt-resume.schema.json`; server-side validation errors re-present the gate with `packet.validation_errors` rendered inline (FR-DEC-7).

**Fallback path** (`03 §5`): `useCopilotAction({name: "underwriter_decision", renderAndWaitForResponse})` rendering the same `DecisionForm` — identical resume schema, swap is one hook.

## 7. `AuditTimeline` (FR-UI-4)

- Header: **chain status badge** from `GET /loans/{id}/audit/verify` — green "Chain verified ✓ (N events)" / red "INTEGRITY FAILURE at seq …"; sealed badge with snapshot hash (copyable); **Replay button** → `POST /loans/{id}/replay` → green "Reproducible ✓" or diff viewer.
- Body: virtualized timeline of events (icon per type, actor, timestamp, expandable payload viewer with PII-masked rendering); filters by event_type group (LLM / rules / human / state / adapters) and text search.
- Footer: "Export audit file" → `GET /loans/{id}/audit/export`.

## 8. Sidebar chat

`CopilotSidebar` (labels: "Underwriting Copilot"), default-open on deep-dive. Grounding: `useCopilotReadable` exposes the selected loan's summary + status; server tools per `09 §7`. Suggested prompts (`useCopilotChatSuggestions` or static chips): "Why is the DTI high?", "What conditions are still open?", "Explain rule DTI-001's result", "Draft the VOE condition text", "Summarize this file's risks". A visible disclaimer chip: "Chat is read-only; decisions happen at the Decision tab."

## 9. Empty/edge states

Loan not yet run → Overview shows "Run underwriting" CTA (`POST /loans/{id}/run`). Suspended → banner with re-run CTA. OFAC-suspended → prominent mandatory-review banner. SSE disconnect during a run → reconnect via AG-UI (HttpAgent handles it); the stepper re-hydrates from `GET /loans/{id}` (REST remains authoritative).
