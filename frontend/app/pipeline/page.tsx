/** Underwriting queue (specs/13 §3). */
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type QueueRow } from "@/lib/api";

const STATUS_CHIP: Record<string, string> = {
  received: "bg-stone-200 text-stone-700",
  ready_for_decision: "bg-amber-100 text-amber-800",
  suspended: "bg-orange-100 text-orange-800",
  approve_with_conditions: "bg-emerald-100 text-emerald-800",
  decline: "bg-red-100 text-red-800",
  counteroffer: "bg-blue-100 text-blue-800",
  suspend: "bg-orange-100 text-orange-800",
};

export default function PipelinePage() {
  const [rows, setRows] = useState<QueueRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .queue()
      .then((data) => setRows(data.items))
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-extrabold">UA — Underwriting pipeline</h1>
        <p className="text-sm text-stone-500">
          Synthetic loan packages · human decision required on every file ·
          full audit trail
        </p>
      </header>
      {error && <p className="text-red-600">{error}</p>}
      <div className="overflow-hidden rounded-xl border border-stone-200 bg-white shadow-sm">
        <table className="w-full text-sm" data-testid="queue">
          <thead className="bg-stone-50 text-left text-xs uppercase text-stone-500">
            <tr>
              <th className="px-4 py-2">Borrower</th>
              <th className="px-4 py-2">Amount</th>
              <th className="px-4 py-2">Purpose</th>
              <th className="px-4 py-2">State</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Suggested</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.application_id}
                className="border-t border-stone-100 hover:bg-blue-50/40"
              >
                <td className="px-4 py-2">
                  <Link
                    className="font-semibold text-blue-800 hover:underline"
                    href={`/loans/${row.application_id}`}
                    data-testid={`loan-${row.application_id}`}
                  >
                    {row.borrower_name}
                  </Link>
                  <div className="font-mono text-[10px] text-stone-400">
                    {row.application_id}
                  </div>
                </td>
                <td className="px-4 py-2 tabular-nums">${row.loan_amount}</td>
                <td className="px-4 py-2">
                  {row.purpose.replace(/_/g, " ")} · {row.occupancy}
                </td>
                <td className="px-4 py-2">{row.state}</td>
                <td className="px-4 py-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-bold ${STATUS_CHIP[row.status] ?? "bg-stone-100"}`}
                  >
                    {row.status.replace(/_/g, " ")}
                  </span>
                </td>
                <td className="px-4 py-2 text-xs text-stone-500">
                  {row.suggested_action?.replace(/_/g, " ") ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
