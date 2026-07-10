/** Audit timeline (specs/13 §7): chain-verified badge, replay button,
 * filterable event browsing, JSON export (FR-UI-4). */
"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

const TYPE_ICON: Record<string, string> = {
  package_accepted: "📦", state_change: "🔀", llm_call: "🤖",
  adapter_call: "🔌", discrepancy_found: "⚖️", red_flag: "🚩",
  rule_eval_batch: "📏", aus_run: "🎯", condition_created: "📋",
  decision_packet_ready: "📨", human_action: "🧑‍⚖️", override: "✍️",
  adverse_action_generated: "📜", hmda_action_taken: "🏛️",
  tool_call: "🔧", node_error: "💥", seal: "🔏",
};

const GROUPS: Record<string, string[]> = {
  all: [],
  llm: ["llm_call", "tool_call"],
  rules: ["rule_eval_batch", "aus_run"],
  human: ["human_action", "override", "decision_packet_ready"],
  findings: ["red_flag", "discrepancy_found", "condition_created"],
  outcome: ["adverse_action_generated", "hmda_action_taken", "seal",
            "state_change"],
};

export function AuditTimeline({ applicationId }: { applicationId: string }) {
  const [events, setEvents] = useState<any[]>([]);
  const [verify, setVerify] = useState<any | null>(null);
  const [replayResult, setReplayResult] = useState<any | null>(null);
  const [group, setGroup] = useState("all");
  const [expanded, setExpanded] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    const [auditData, verifyData] = await Promise.all([
      api.audit(applicationId),
      api.auditVerify(applicationId),
    ]);
    setEvents(auditData.items);
    setVerify(verifyData);
  }, [applicationId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const visible = events.filter(
    (event) => group === "all" || GROUPS[group].includes(event.event_type),
  );

  return (
    <div data-testid="audit-timeline">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        {verify &&
          (verify.chain_ok ? (
            <span
              data-testid="chain-badge"
              className="rounded-full bg-emerald-100 px-3 py-1 text-sm font-bold text-emerald-800"
            >
              ✓ Chain verified ({verify.events_total} events,{" "}
              {verify.app_events} this loan)
            </span>
          ) : (
            <span
              data-testid="chain-badge"
              className="rounded-full bg-red-600 px-3 py-1 text-sm font-bold text-white"
            >
              ✗ INTEGRITY FAILURE at seq {verify.first_broken_seq}
            </span>
          ))}
        {verify?.sealed && (
          <span className="rounded-full bg-stone-800 px-3 py-1 text-xs font-mono text-white">
            🔏 sealed {verify.snapshot_hash?.slice(0, 16)}…
          </span>
        )}
        {verify?.sealed && (
          <button
            data-testid="replay-btn"
            onClick={async () => setReplayResult(await api.replay(applicationId))}
            className="rounded bg-blue-700 px-3 py-1 text-sm font-semibold text-white hover:bg-blue-800"
          >
            Replay decision
          </button>
        )}
        {replayResult && (
          <span
            data-testid="replay-result"
            className={`rounded-full px-3 py-1 text-sm font-bold ${
              replayResult.identical
                ? "bg-emerald-100 text-emerald-800"
                : "bg-red-100 text-red-800"
            }`}
          >
            {replayResult.identical
              ? "✓ Reproducible — byte-identical outcome"
              : `✗ DIVERGED: ${replayResult.diffs[0] ?? ""}`}
          </span>
        )}
        <a
          href={api.exportUrl(applicationId)}
          className="ml-auto rounded border border-stone-300 px-3 py-1 text-sm hover:bg-stone-50"
        >
          ⬇ Export audit file
        </a>
      </div>

      <div className="mb-2 flex gap-1">
        {Object.keys(GROUPS).map((name) => (
          <button
            key={name}
            onClick={() => setGroup(name)}
            className={`rounded px-2 py-0.5 text-xs font-semibold ${
              group === name
                ? "bg-stone-800 text-white"
                : "bg-stone-100 hover:bg-stone-200"
            }`}
          >
            {name}
          </button>
        ))}
        <button
          onClick={() => void refresh()}
          className="ml-auto rounded px-2 py-0.5 text-xs text-stone-500 hover:bg-stone-100"
        >
          ↻ refresh
        </button>
      </div>

      <ol className="space-y-1">
        {visible.map((event) => (
          <li
            key={event.seq}
            className="rounded border border-stone-200 bg-white text-sm"
          >
            <button
              className="flex w-full items-center gap-2 p-2 text-left hover:bg-stone-50"
              onClick={() =>
                setExpanded(expanded === event.seq ? null : event.seq)
              }
            >
              <span>{TYPE_ICON[event.event_type] ?? "•"}</span>
              <span className="font-mono text-xs text-stone-400">
                #{event.seq}
              </span>
              <span className="font-semibold">{event.event_type}</span>
              <span className="text-xs text-stone-500">{event.actor}</span>
              <span className="ml-auto text-xs text-stone-400">
                {event.created_at}
              </span>
            </button>
            {expanded === event.seq && (
              <pre className="overflow-x-auto border-t border-stone-100 bg-stone-50 p-2 text-[11px]">
                {JSON.stringify(event.payload, null, 2)}
                {"\n"}hash: {event.hash}
                {"\n"}prev: {event.prev_hash}
              </pre>
            )}
          </li>
        ))}
      </ol>
      {visible.length === 0 && (
        <p className="text-sm text-stone-500">No events in this group yet.</p>
      )}
    </div>
  );
}
