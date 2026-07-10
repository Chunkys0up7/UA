/**
 * Phase-0 walking-skeleton gate page (specs/16 §3, T-P0-1).
 *
 * Proves the highest-risk integration in the browser before any domain
 * code: run the underwriter agent → LangGraph interrupt() surfaces via
 * AG-UI → gate renders → resume with the approve payload → run completes.
 *
 * DEVIATION D-P0-1: the run is started via the bound module-level
 * HttpAgent (lib/agents.ts) because useCoAgent's returned run/start are
 * unbound in @copilotkit/react-core 1.57–1.62 (see DEVIATIONS.md). The
 * interrupt is consumed from the agent's AG-UI event stream
 * (CUSTOM name="on_interrupt"); useLangGraphInterrupt remains registered
 * as a probe. Resume payload shape is a miniature of
 * specs/schemas/interrupt-resume.schema.json#/$defs/resume, so the
 * Phase 5 DecisionGate swap is payload-compatible.
 */
"use client";

import { useCoAgent, useLangGraphInterrupt } from "@copilotkit/react-core";
import { useEffect, useState } from "react";
import { underwriterAgent } from "@/lib/agents";

interface SkeletonState {
  application_id?: string;
  progress?: { id: string; label: string; status: string; detail: string }[];
  decision_packet?: Record<string, unknown> | null;
  human_decision?: Record<string, unknown> | null;
}

export default function SkeletonGatePage() {
  const [log, setLog] = useState<string[]>([]);
  const [interruptPacket, setInterruptPacket] = useState<Record<string, unknown> | null>(null);
  const [agentState, setAgentState] = useState<SkeletonState>({});
  const [busy, setBusy] = useState(false);
  const append = (line: string) =>
    setLog((l) => [...l, `${new Date().toISOString()} ${line}`]);

  // Shared-state subscription via the hook (works — only run/start are broken).
  const { state: hookState } = useCoAgent<SkeletonState>({
    name: "underwriter",
    initialState: { application_id: "APP-SKELETON-001" },
  });

  // Probe: does the built-in interrupt hook fire against the ag-ui mount?
  useLangGraphInterrupt({
    render: ({ event, resolve }) => {
      append("useLangGraphInterrupt fired (probe)");
      return (
        <button onClick={() => resolve(JSON.stringify({ action: "approve_with_conditions" }))}>
          probe-resolve
        </button>
      );
    },
  });

  // Primary path: consume the interrupt from the agent event stream.
  useEffect(() => {
    const { unsubscribe } = underwriterAgent.subscribe({
      onCustomEvent: ({ event }: { event: { name?: string; rawEvent?: { value?: unknown } } }) => {
        if (event.name === "on_interrupt") {
          const value = (event as { value?: unknown }).value;
          const packet = typeof value === "string" ? JSON.parse(value) : (value ?? {});
          setInterruptPacket(packet as Record<string, unknown>);
          append("interrupt received via AG-UI stream");
        }
      },
      onStateChanged: ({ state }: { state: SkeletonState }) => setAgentState(state),
      onRunFinishedEvent: () => append("run finished"),
      onRunFailed: ({ error }: { error: Error }) => append(`run FAILED: ${error.message}`),
    });
    return () => unsubscribe();
  }, []);

  const startRun = () => {
    setBusy(true);
    append("run started (bound agent.runAgent)");
    underwriterAgent.state = { application_id: "APP-SKELETON-001" };
    underwriterAgent
      .runAgent({ forwardedProps: {} })
      .then(() => append("runAgent resolved"))
      .catch((e: Error) => append(`runAgent FAILED: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const approve = () => {
    setBusy(true);
    setInterruptPacket(null);
    append("resume submitted: approve_with_conditions");
    underwriterAgent
      .runAgent({
        forwardedProps: {
          command: {
            resume: JSON.stringify({
              action: "approve_with_conditions",
              underwriter_id: "uw-p0-tester",
              reason_codes: [],
            }),
          },
        },
      })
      .then(() => append("resume resolved — graph completed"))
      .catch((e: Error) => append(`resume FAILED: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const shownState = Object.keys(agentState).length ? agentState : hookState;

  return (
    <main style={{ maxWidth: 720, margin: "40px auto", fontFamily: "ui-sans-serif" }}>
      <h1 style={{ fontSize: 24, fontWeight: 800 }}>UA — Phase 0 walking skeleton</h1>
      <p style={{ color: "#57534e", margin: "8px 0 16px" }}>
        Gate T-P0-1: run → interrupt renders → approve → run completes.
      </p>
      <button
        data-testid="run-btn"
        disabled={busy}
        style={{ background: busy ? "#a8a29e" : "#1d4ed8", color: "white", padding: "10px 20px", borderRadius: 6 }}
        onClick={startRun}
      >
        {busy ? "Working…" : "Run underwriter skeleton"}
      </button>

      {interruptPacket && (
        <div data-testid="decision-gate" style={{ border: "2px solid #b45309", borderRadius: 8, padding: 16, margin: "16px 0" }}>
          <h3 style={{ fontWeight: 700 }}>Decision gate (interrupt received)</h3>
          <pre style={{ fontSize: 12, background: "#f5f5f4", padding: 8, overflowX: "auto" }}>
            {JSON.stringify(interruptPacket, null, 2)}
          </pre>
          <button
            data-testid="approve-btn"
            style={{ background: "#166534", color: "white", padding: "8px 16px", borderRadius: 6 }}
            onClick={approve}
          >
            Approve (resume graph)
          </button>
        </div>
      )}

      <h2 style={{ fontWeight: 700, marginTop: 24 }}>Agent state</h2>
      <pre data-testid="agent-state" style={{ fontSize: 12, background: "#f5f5f4", padding: 8, overflowX: "auto" }}>
        {JSON.stringify(shownState, null, 2)}
      </pre>

      <h2 style={{ fontWeight: 700, marginTop: 16 }}>Event log</h2>
      <pre data-testid="event-log" style={{ fontSize: 12, background: "#f5f5f4", padding: 8 }}>
        {log.join("\n") || "(empty)"}
      </pre>
    </main>
  );
}
