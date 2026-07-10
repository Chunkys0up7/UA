/** Typed fetchers for the workbench data plane (specs/12). */

const BACKEND =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export interface QueueRow {
  application_id: string;
  status: string;
  borrower_name: string;
  loan_amount: string;
  purpose: string;
  occupancy: string;
  state: string;
  suggested_action: string | null;
  interrupted: boolean;
}

export interface RuleEvaluation {
  rule_id: string;
  ruleset: string;
  description: string;
  severity: string;
  outcome: string;
  reason_code: string | null;
  citation: string | null;
  inputs: { path: string; value: string; lineage_ref: string | null }[];
}

export interface LoanDetail {
  application_id: string;
  status: string;
  application: Record<string, string | number>;
  four_cs: any | null;
  rules: {
    overall: string;
    pack_version: string;
    overlay_pack_version: string;
    evaluations: RuleEvaluation[];
  } | null;
  aus: {
    recommendation: string;
    simulator_version: string;
    breakdown: Record<string, number>;
    total_points: number;
    messages: { message_id: string; category: string; text: string }[];
  } | null;
  conditions: any[];
  red_flags: any[];
  atr: any[];
  discrepancies: any[];
  packet: any | null;
}

export interface LineageNode {
  ref: string;
  kind: string;
  label: string;
  value: string;
  method: string | null;
  parents: string[];
  source_id: string | null;
  meta: Record<string, string>;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BACKEND}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

export const api = {
  queue: () => get<{ items: QueueRow[] }>("/loans"),
  detail: (id: string) => get<LoanDetail>(`/loans/${id}`),
  lineage: (id: string, ref: string) =>
    get<{ node: LineageNode; ancestors: LineageNode[] }>(
      `/lineage/${id}/${ref}`,
    ),
  audit: (id: string) =>
    get<{ items: any[] }>(`/loans/${id}/audit?limit=500`),
  auditVerify: (id: string) =>
    get<{
      chain_ok: boolean;
      events_total: number;
      app_events: number;
      sealed: boolean;
      snapshot_hash: string | null;
    }>(`/loans/${id}/audit/verify`),
  decision: (id: string) => get<any>(`/loans/${id}/decision`),
  decisionHistory: (id: string) =>
    get<{ decisions: any[]; human_actions: any[] }>(`/loans/${id}/decisions`),
  adverseAction: (id: string) => get<any>(`/loans/${id}/adverse-action`),
  replay: async (id: string) => {
    const response = await fetch(`${BACKEND}/loans/${id}/replay`, {
      method: "POST",
    });
    if (!response.ok) throw new Error(`replay: ${response.status}`);
    return response.json() as Promise<{ identical: boolean; diffs: string[] }>;
  },
  exportUrl: (id: string) => `${BACKEND}/loans/${id}/audit/export`,
};
