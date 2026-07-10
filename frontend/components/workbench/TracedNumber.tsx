/**
 * <TracedNumber /> + lineage popover — the workbench's signature
 * interaction (specs/13 §4, FR-LIN-2/HR-3): click any computed number and
 * walk its derivation down to the extracted document fields (with
 * confidence, prompt@version, model id).
 */
"use client";

import { useState } from "react";
import { api, type LineageNode } from "@/lib/api";

const KIND_BADGE: Record<string, string> = {
  calculation: "bg-blue-100 text-blue-800",
  extracted_field: "bg-emerald-100 text-emerald-800",
  package_stated: "bg-stone-200 text-stone-700",
  constant_policy: "bg-purple-100 text-purple-800",
  adapter_result: "bg-amber-100 text-amber-800",
};

export function TracedNumber({
  applicationId,
  value,
  lineageRef,
  suffix = "",
  className = "",
}: {
  applicationId: string;
  value: string | number;
  lineageRef?: string | null;
  suffix?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [chain, setChain] = useState<{
    node: LineageNode;
    ancestors: LineageNode[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!lineageRef) {
    return (
      <span className={`tabular-nums ${className}`}>
        {value}
        {suffix}
      </span>
    );
  }

  const openPopover = async () => {
    setOpen(true);
    if (!chain) {
      try {
        setChain(await api.lineage(applicationId, lineageRef));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }
  };

  return (
    <span className="relative inline-block">
      <button
        data-testid={`traced-${lineageRef.slice(0, 10)}`}
        onClick={openPopover}
        className={`tabular-nums underline decoration-dotted decoration-blue-400 underline-offset-2 hover:bg-blue-50 rounded px-0.5 ${className}`}
        title="Click to trace this number to its sources"
      >
        {value}
        {suffix}
      </button>
      {open && (
        <div
          data-testid="lineage-popover"
          className="absolute z-50 left-0 top-full mt-1 w-[26rem] max-h-96 overflow-auto rounded-lg border border-stone-300 bg-white p-3 shadow-xl text-left"
        >
          <div className="flex justify-between items-center mb-2">
            <span className="text-xs font-bold text-stone-500 uppercase">
              Lineage
            </span>
            <button
              className="text-stone-400 hover:text-stone-700 text-sm"
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
              }}
            >
              ×
            </button>
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
          {chain && (
            <ul className="space-y-1.5">
              <LineageRow node={chain.node} isRoot />
              {chain.ancestors.map((ancestor) => (
                <LineageRow key={ancestor.ref} node={ancestor} />
              ))}
            </ul>
          )}
        </div>
      )}
    </span>
  );
}

function LineageRow({
  node,
  isRoot = false,
}: {
  node: LineageNode;
  isRoot?: boolean;
}) {
  return (
    <li
      className={`rounded border p-1.5 text-xs ${
        isRoot ? "border-blue-300 bg-blue-50" : "border-stone-200"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`rounded px-1 py-0.5 text-[10px] font-semibold ${
            KIND_BADGE[node.kind] ?? "bg-stone-100"
          }`}
        >
          {node.kind.replace("_", " ")}
        </span>
        <span className="font-mono text-stone-600">{node.label}</span>
        <span className="ml-auto font-bold tabular-nums">{node.value}</span>
      </div>
      {(node.method || node.source_id || Object.keys(node.meta).length > 0) && (
        <div className="mt-1 text-[10px] text-stone-500 space-x-2">
          {node.method && <span>method: {node.method}</span>}
          {node.source_id && <span>source: {node.source_id}</span>}
          {node.meta.confidence && (
            <span>confidence: {node.meta.confidence}</span>
          )}
          {node.meta.prompt && <span>prompt: {node.meta.prompt}</span>}
          {node.meta.model && <span>model: {node.meta.model}</span>}
          {node.meta.pack_version && (
            <span>pack: {node.meta.pack_version}</span>
          )}
        </div>
      )}
    </li>
  );
}
