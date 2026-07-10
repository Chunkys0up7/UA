/**
 * DecisionGate (specs/13 §6): renders the interrupt's decision packet,
 * collects the resume payload (schemas/interrupt-resume.schema.json).
 * The reason-code picker lists ONLY codes bound to actually-failed rules
 * (FR-DEC-2); overrides demand justification; four-eyes enforced
 * client-side AND server-side (server re-presents on violation).
 */
"use client";

import { useState } from "react";

const ACTIONS = [
  ["approve_with_conditions", "Approve with conditions"],
  ["suspend", "Suspend"],
  ["decline", "Decline"],
  ["counteroffer", "Counteroffer"],
] as const;

export interface ResumePayload {
  action: string;
  underwriter_id: string;
  second_reviewer_id?: string | null;
  reason_codes?: string[];
  justification?: string | null;
  notes?: string | null;
  counteroffer_terms?: { loan_amount: string } | null;
}

export function DecisionGate({
  packet,
  busy,
  onSubmit,
}: {
  packet: any;
  busy: boolean;
  onSubmit: (resume: ResumePayload) => void;
}) {
  const suggested = packet.suggested_action as string;
  const [action, setAction] = useState<string>(suggested);
  const [underwriter, setUnderwriter] = useState("uw-1042");
  const [second, setSecond] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [justification, setJustification] = useState("");
  const [notes, setNotes] = useState("");
  const hints: any[] = packet.counteroffer_hints ?? [];
  const [counterAmount, setCounterAmount] = useState(
    hints[0]?.max_value ?? "",
  );

  const isOverride = action !== suggested;
  const needsSecond = packet.four_eyes_required || action === "decline";
  const serverErrors: string[] = packet.validation_errors ?? [];

  const failedDescriptions: Record<string, string> = {};
  for (const failed of packet.rules?.failed ?? [])
    if (failed.reason_code)
      failedDescriptions[failed.reason_code] = failed.description;

  return (
    <div
      data-testid="decision-gate"
      className="rounded-xl border-2 border-amber-600 bg-amber-50/50 p-5 shadow-lg"
    >
      <h3 className="text-lg font-extrabold">Underwriting decision required</h3>
      <p className="mt-1 text-sm">
        Suggested action:{" "}
        <span className="rounded bg-stone-800 px-2 py-0.5 font-bold text-white">
          {suggested.replace(/_/g, " ")}
        </span>
        <span className="ml-2 text-stone-500">
          (suggestion only — you decide)
        </span>
      </p>

      {serverErrors.length > 0 && (
        <div
          data-testid="gate-errors"
          className="mt-3 rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800"
        >
          <b>The previous submission was rejected:</b>
          <ul className="ml-5 list-disc">
            {serverErrors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {ACTIONS.map(([value, label]) => (
          <button
            key={value}
            data-testid={`action-${value}`}
            onClick={() => setAction(value)}
            className={`rounded-lg border px-3 py-1.5 text-sm font-semibold ${
              action === value
                ? "border-blue-700 bg-blue-700 text-white"
                : "border-stone-300 bg-white hover:bg-stone-50"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {action === "decline" && (
        <div className="mt-4">
          <h4 className="text-sm font-bold">
            Principal reasons (1–4, from failed rules only — ECOA/Reg B)
          </h4>
          {packet.eligible_reason_codes.length === 0 && (
            <p className="text-sm text-red-700">
              No failed rules — decline is not supportable on this file.
            </p>
          )}
          <div className="mt-1 space-y-1">
            {packet.eligible_reason_codes.map((code: string) => (
              <label key={code} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  data-testid={`code-${code}`}
                  checked={codes.includes(code)}
                  onChange={(e) =>
                    setCodes(
                      e.target.checked
                        ? [...codes, code].slice(0, 4)
                        : codes.filter((c) => c !== code),
                    )
                  }
                />
                <span>
                  <span className="font-mono font-semibold">{code}</span>
                  {failedDescriptions[code] && (
                    <span className="text-stone-500">
                      {" "}
                      — {failedDescriptions[code]}
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>
        </div>
      )}

      {action === "counteroffer" && (
        <div className="mt-4">
          <h4 className="text-sm font-bold">Counteroffer terms</h4>
          {hints.length > 0 && (
            <p className="text-xs text-stone-500">
              Hint: max amount passing {hints[0].rule_id} = $
              {hints[0].max_value}
              {hints[0].achieved_ratio &&
                ` (back DTI ${hints[0].achieved_ratio}%)`}
            </p>
          )}
          <input
            data-testid="counter-amount"
            className="mt-1 w-48 rounded border border-stone-300 p-1.5 text-sm"
            value={counterAmount}
            onChange={(e) => setCounterAmount(e.target.value)}
            placeholder="loan amount"
          />
        </div>
      )}

      {isOverride && (
        <div className="mt-4">
          <h4 className="text-sm font-bold text-red-800">
            Override — justification required (min 20 chars, recorded in the
            audit trail)
          </h4>
          <textarea
            data-testid="justification"
            className="mt-1 w-full rounded border border-stone-300 p-2 text-sm"
            rows={2}
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            placeholder="Why are you deviating from the suggested action?"
          />
        </div>
      )}

      <div className="mt-4">
        <h4 className="text-sm font-bold">
          Underwriter notes{" "}
          <span className="font-normal text-stone-500">
            (optional — recorded permanently with the decision)
          </span>
        </h4>
        <textarea
          data-testid="decision-notes"
          className="mt-1 w-full rounded border border-stone-300 p-2 text-sm"
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Rationale, compensating-factor commentary, follow-ups…"
        />
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="block text-xs font-bold text-stone-500">
            Underwriter ID
          </span>
          <input
            data-testid="underwriter-id"
            className="rounded border border-stone-300 p-1.5"
            value={underwriter}
            onChange={(e) => setUnderwriter(e.target.value)}
          />
        </label>
        {needsSecond && (
          <label className="text-sm">
            <span className="block text-xs font-bold text-stone-500">
              Second reviewer (four-eyes)
            </span>
            <input
              data-testid="second-reviewer"
              className="rounded border border-stone-300 p-1.5"
              value={second}
              onChange={(e) => setSecond(e.target.value)}
              placeholder="uw-…"
            />
          </label>
        )}
        <button
          data-testid="submit-decision"
          disabled={busy}
          onClick={() =>
            onSubmit({
              action,
              underwriter_id: underwriter,
              second_reviewer_id: second || null,
              reason_codes: action === "decline" ? codes : [],
              justification: justification || null,
              notes: notes || null,
              counteroffer_terms:
                action === "counteroffer"
                  ? { loan_amount: counterAmount }
                  : null,
            })
          }
          className="rounded-lg bg-emerald-700 px-5 py-2 font-bold text-white hover:bg-emerald-800 disabled:bg-stone-400"
        >
          {busy ? "Submitting…" : "Submit decision"}
        </button>
      </div>
    </div>
  );
}
