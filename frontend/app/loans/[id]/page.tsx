/**
 * Loan deep-dive workbench (specs/13 §4-§7): run the agent, watch live
 * progress, drill into every number, decide at the gate, inspect the
 * audit chain. Runs start via the bound HttpAgent (DEVIATION D-P0-1);
 * interrupts arrive on its AG-UI event stream.
 */
"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { underwriterAgent } from "@/lib/agents";
import { api, type LoanDetail } from "@/lib/api";
import { DecisionGate, type ResumePayload } from "@/components/copilot/DecisionGate";
import { AuditTimeline } from "@/components/workbench/AuditTimeline";
import {
  AtrChecklist, AusCard, Card, ConditionsBoard, FourCsGrid, RedFlagsPanel,
  RulesTable,
} from "@/components/workbench/Panels";

const TABS = ["Overview", "4 Cs", "ATR", "Rules & AUS", "Conditions",
              "Red flags", "Decision", "Audit"] as const;

export default function LoanPage({ params }: { params: { id: string } }) {
  const applicationId = params.id;
  const [detail, setDetail] = useState<LoanDetail | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [busy, setBusy] = useState(false);
  const [interruptPacket, setInterruptPacket] = useState<any | null>(null);
  const [agentState, setAgentState] = useState<any>({});
  const [decisionInfo, setDecisionInfo] = useState<any | null>(null);
  const [adverse, setAdverse] = useState<any | null>(null);
  const packetRef = useRef<any | null>(null);

  const refresh = useCallback(async () => {
    const data = await api.detail(applicationId);
    setDetail(data);
    if (["decline", "approve_with_conditions", "suspend", "counteroffer"]
        .includes(data.status)) {
      api.decision(applicationId).then(setDecisionInfo).catch(() => null);
      api.adverseAction(applicationId).then(setAdverse).catch(() => null);
    }
    if (data.status === "ready_for_decision" && data.packet) {
      setInterruptPacket(data.packet);
      packetRef.current = data.packet;
    }
    return data;
  }, [applicationId]);

  useEffect(() => {
    void refresh();
    const { unsubscribe } = underwriterAgent.subscribe({
      onCustomEvent: ({ event }: { event: any }) => {
        if (event.name === "on_interrupt") {
          const value = event.value;
          const packet = typeof value === "string" ? JSON.parse(value) : value;
          setInterruptPacket(packet);
          packetRef.current = packet;
        }
      },
      onStateChanged: ({ state }: { state: any }) => setAgentState(state),
    });
    return () => unsubscribe();
  }, [refresh]);

  const runUnderwriting = () => {
    setBusy(true);
    setInterruptPacket(null);
    underwriterAgent.threadId = applicationId;
    underwriterAgent.state = { application_id: applicationId };
    underwriterAgent
      .runAgent({ forwardedProps: {} })
      .catch((e: Error) => alert(`run failed: ${e.message}`))
      .finally(async () => {
        setBusy(false);
        await refresh();
        setTab("Decision");
      });
  };

  const submitDecision = (resume: ResumePayload) => {
    setBusy(true);
    setInterruptPacket(null);
    underwriterAgent.threadId = applicationId;
    underwriterAgent
      .runAgent({
        forwardedProps: { command: { resume: JSON.stringify(resume) } },
      })
      .catch((e: Error) => alert(`resume failed: ${e.message}`))
      .finally(async () => {
        setBusy(false);
        await refresh();
      });
  };

  if (!detail) return <main className="p-8">Loading…</main>;
  const app = detail.application;
  const progress: any[] = agentState.progress ?? [];

  return (
    <main className="mx-auto max-w-6xl p-6">
      <Link href="/pipeline" className="text-sm text-blue-700 hover:underline">
        ← Pipeline
      </Link>
      <header className="mb-4 mt-1 flex flex-wrap items-center gap-4">
        <div>
          <h1 className="text-2xl font-extrabold">{app.borrower_name}</h1>
          <p className="text-sm text-stone-500">
            ${app.loan_amount} · {String(app.purpose).replace(/_/g, " ")} ·{" "}
            {app.occupancy} · {app.property_state} · rate {app.note_rate}% ·
            MLO NMLS {app.mlo_nmls_id}
          </p>
        </div>
        <span
          data-testid="status-chip"
          className="rounded-full bg-stone-800 px-3 py-1 text-sm font-bold text-white"
        >
          {detail.status.replace(/_/g, " ")}
        </span>
        {detail.status === "received" && (
          <button
            data-testid="run-underwriting"
            disabled={busy}
            onClick={runUnderwriting}
            className="rounded-lg bg-blue-700 px-5 py-2 font-bold text-white hover:bg-blue-800 disabled:bg-stone-400"
          >
            {busy ? "Underwriting…" : "▶ Run underwriting"}
          </button>
        )}
      </header>

      {busy && progress.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1" data-testid="progress">
          {progress.map((stage: any) => (
            <span
              key={stage.id}
              className={`rounded px-2 py-0.5 text-[10px] font-semibold ${
                stage.status === "done"
                  ? "bg-emerald-100 text-emerald-800"
                  : "bg-stone-100 text-stone-500"
              }`}
            >
              {stage.label}
            </span>
          ))}
        </div>
      )}

      <nav className="mb-4 flex flex-wrap gap-1 border-b border-stone-200">
        {TABS.map((name) => (
          <button
            key={name}
            data-testid={`tab-${name.replace(/[^a-zA-Z]/g, "")}`}
            onClick={() => setTab(name)}
            className={`px-3 py-2 text-sm font-semibold ${
              tab === name
                ? "border-b-2 border-blue-700 text-blue-800"
                : "text-stone-500 hover:text-stone-800"
            }`}
          >
            {name}
            {name === "Decision" && interruptPacket ? " ⏸" : ""}
          </button>
        ))}
      </nav>

      {tab === "Overview" && (
        <div className="space-y-4">
          <Card title="File summary">
            <p className="text-sm">
              {String(app.property_type).replace(/_/g, " ")} in{" "}
              {app.property_state}; {app.term_months}-month term. Status:{" "}
              <b>{detail.status.replace(/_/g, " ")}</b>.
            </p>
            {detail.rules && (
              <p className="mt-2 text-sm">
                Policy rollup: <b>{detail.rules.overall}</b> under{" "}
                {detail.rules.pack_version} + {detail.rules.overlay_pack_version}.
                AUS: <b>{detail.aus?.recommendation}</b> (advisory).
              </p>
            )}
          </Card>
          <FourCsGrid detail={detail} />
        </div>
      )}
      {tab === "4 Cs" && <FourCsGrid detail={detail} />}
      {tab === "ATR" && <AtrChecklist detail={detail} />}
      {tab === "Rules & AUS" && (
        <div className="space-y-4">
          <AusCard detail={detail} />
          <RulesTable detail={detail} />
        </div>
      )}
      {tab === "Conditions" && <ConditionsBoard detail={detail} />}
      {tab === "Red flags" && <RedFlagsPanel detail={detail} />}
      {tab === "Decision" && (
        <div className="space-y-4">
          {interruptPacket && (
            <DecisionGate
              packet={interruptPacket}
              busy={busy}
              onSubmit={submitDecision}
            />
          )}
          {!interruptPacket && decisionInfo && (
            <Card title="Decision" accent="border-emerald-300">
              <p className="text-lg font-bold" data-testid="final-action">
                {String(decisionInfo.decision.action).replace(/_/g, " ")}
              </p>
              <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
                <dt className="text-stone-500">Decided by</dt>
                <dd>{decisionInfo.decision.decided_by}</dd>
                <dt className="text-stone-500">Second reviewer</dt>
                <dd>{decisionInfo.decision.second_reviewer ?? "—"}</dd>
                <dt className="text-stone-500">HMDA action taken</dt>
                <dd>{decisionInfo.decision.hmda_action_taken ?? "pending"}</dd>
                <dt className="text-stone-500">Snapshot</dt>
                <dd className="font-mono text-xs">
                  {decisionInfo.snapshot_hash?.slice(0, 24)}…
                </dd>
                <dt className="text-stone-500">Versions</dt>
                <dd className="text-xs">
                  {decisionInfo.versions.policy_pack} ·{" "}
                  {decisionInfo.versions.state_overlay_pack} ·{" "}
                  {decisionInfo.versions.aus_simulator} · LLM{" "}
                  {decisionInfo.versions.llm_provider}
                </dd>
              </dl>
            </Card>
          )}
          {adverse && (
            <Card title="Adverse-action notice (ECOA/Reg B + FCRA §609(g))"
                  accent="border-red-200">
              <pre
                data-testid="adverse-notice"
                className="whitespace-pre-wrap rounded bg-stone-50 p-3 text-xs"
              >
                {adverse.body_text}
              </pre>
            </Card>
          )}
          {!interruptPacket && !decisionInfo && (
            <p className="text-sm text-stone-500">
              Run underwriting to reach the decision gate.
            </p>
          )}
        </div>
      )}
      {tab === "Audit" && <AuditTimeline applicationId={applicationId} />}
    </main>
  );
}
