/** Workbench analysis panels (specs/13 §4): 4 Cs with lineage drill-down,
 * ATR checklist, rules table with statutory citations, AUS card,
 * conditions board, red flags. */
"use client";

import { type LoanDetail, type RuleEvaluation } from "@/lib/api";
import { TracedNumber } from "./TracedNumber";

const OUTCOME_CHIP: Record<string, string> = {
  pass: "bg-emerald-100 text-emerald-800",
  fail: "bg-red-100 text-red-800",
  refer: "bg-amber-100 text-amber-800",
  not_applicable: "bg-stone-100 text-stone-500",
};

const SEVERITY_CHIP: Record<string, string> = {
  critical: "bg-red-600 text-white",
  elevated: "bg-amber-500 text-white",
  info: "bg-stone-300 text-stone-800",
};

export function Card({
  title,
  children,
  accent = "",
}: {
  title: string;
  children: React.ReactNode;
  accent?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-stone-200 bg-white p-4 shadow-sm ${accent}`}
    >
      <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-stone-500">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Metric({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 border-b border-stone-100 last:border-0">
      <span className="text-sm text-stone-600">{label}</span>
      <span className="text-sm font-semibold">{children}</span>
    </div>
  );
}

export function FourCsGrid({ detail }: { detail: LoanDetail }) {
  const fc = detail.four_cs;
  const id = detail.application_id;
  if (!fc)
    return (
      <p className="text-sm text-stone-500">
        Run underwriting to populate the 4 Cs analysis.
      </p>
    );
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2" data-testid="four-cs">
      <Card title="Credit">
        <Metric label="Representative score">
          <TracedNumber
            applicationId={id}
            value={fc.credit.representative_score}
            lineageRef={fc.credit.representative_score_ref}
          />
        </Metric>
        <Metric label="Open disputes">{fc.credit.open_disputes}</Metric>
      </Card>
      <Card title="Capacity">
        <Metric label="Back-end DTI">
          <TracedNumber
            applicationId={id}
            value={fc.capacity.back_ratio}
            lineageRef={fc.capacity.back_ratio_ref}
            suffix="%"
          />
        </Metric>
        <Metric label="Front-end DTI">
          <TracedNumber
            applicationId={id}
            value={fc.capacity.front_ratio}
            lineageRef={fc.capacity.front_ratio_ref}
            suffix="%"
          />
        </Metric>
        <Metric label="Qualifying income / mo">
          <TracedNumber
            applicationId={id}
            value={`$${fc.capacity.qualifying_income_monthly}`}
            lineageRef={fc.capacity.qualifying_income_ref}
          />
        </Metric>
        <Metric label="PITIA">
          <TracedNumber
            applicationId={id}
            value={`$${fc.capacity.pitia.total}`}
            lineageRef={fc.capacity.pitia.total_ref}
          />
        </Metric>
      </Card>
      <Card title="Capital">
        <Metric label="Reserves (months)">
          <TracedNumber
            applicationId={id}
            value={fc.capital.reserves_months}
            lineageRef={fc.capital.reserves_ref}
          />
        </Metric>
        <Metric label="Unsourced large deposits">
          {fc.capital.unsourced_deposits}
        </Metric>
        <Metric label="Funds to close">${fc.capital.funds_to_close}</Metric>
      </Card>
      <Card title="Collateral">
        <Metric label="LTV">
          <TracedNumber
            applicationId={id}
            value={fc.collateral.ltv}
            lineageRef={fc.collateral.ltv_ref}
            suffix="%"
          />
        </Metric>
        <Metric label="CLTV">
          <TracedNumber
            applicationId={id}
            value={fc.collateral.cltv}
            lineageRef={fc.collateral.cltv_ref}
            suffix="%"
          />
        </Metric>
        <Metric label="Appraised value">
          ${fc.collateral.appraised_value}
        </Metric>
      </Card>
    </div>
  );
}

export function AtrChecklist({ detail }: { detail: LoanDetail }) {
  if (!detail.atr?.length)
    return <p className="text-sm text-stone-500">Run underwriting first.</p>;
  return (
    <Card title="ATR — 12 CFR 1026.43 eight factors">
      <ol className="space-y-1.5">
        {detail.atr.map((factor: any) => (
          <li key={factor.factor_number} className="flex gap-2 text-sm">
            <span
              className={`mt-0.5 h-4 w-4 shrink-0 rounded-full text-center text-[10px] font-bold leading-4 ${
                factor.basis.startsWith("unavailable")
                  ? "bg-amber-400 text-white"
                  : "bg-emerald-500 text-white"
              }`}
            >
              {factor.factor_number}
            </span>
            <span>
              <span className="font-medium">{factor.factor_name}</span>
              <span className="text-stone-500"> — {factor.basis}</span>
            </span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function RulesTable({ detail }: { detail: LoanDetail }) {
  const rules = detail.rules;
  if (!rules)
    return <p className="text-sm text-stone-500">Run underwriting first.</p>;
  return (
    <Card title={`Policy evaluation — ${rules.pack_version} + ${rules.overlay_pack_version}`}>
      <p className="mb-2 text-sm">
        Rollup:{" "}
        <span
          className={`rounded px-2 py-0.5 font-bold ${
            rules.overall === "eligible"
              ? "bg-emerald-100 text-emerald-800"
              : rules.overall === "ineligible"
                ? "bg-red-100 text-red-800"
                : "bg-amber-100 text-amber-800"
          }`}
          data-testid="rules-rollup"
        >
          {rules.overall}
        </span>
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-stone-200 text-left text-stone-500">
              <th className="py-1 pr-2">Rule</th>
              <th className="py-1 pr-2">Outcome</th>
              <th className="py-1 pr-2">Inputs</th>
              <th className="py-1">Authority</th>
            </tr>
          </thead>
          <tbody>
            {rules.evaluations.map((evaluation) => (
              <RuleRow
                key={evaluation.rule_id}
                evaluation={evaluation}
                applicationId={detail.application_id}
              />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function RuleRow({
  evaluation,
  applicationId,
}: {
  evaluation: RuleEvaluation;
  applicationId: string;
}) {
  return (
    <tr className="border-b border-stone-100 align-top">
      <td className="py-1.5 pr-2">
        <div className="font-mono font-semibold">{evaluation.rule_id}</div>
        <div className="text-stone-500 max-w-xs">{evaluation.description}</div>
      </td>
      <td className="py-1.5 pr-2">
        <span
          className={`rounded px-1.5 py-0.5 font-semibold ${OUTCOME_CHIP[evaluation.outcome]}`}
        >
          {evaluation.outcome}
        </span>
        {evaluation.reason_code && (
          <div className="mt-0.5 font-mono text-[10px] text-stone-500">
            {evaluation.reason_code}
          </div>
        )}
      </td>
      <td className="py-1.5 pr-2">
        {evaluation.inputs.map((input) => (
          <div key={input.path} className="whitespace-nowrap">
            <span className="text-stone-500">{input.path} = </span>
            <TracedNumber
              applicationId={applicationId}
              value={input.value}
              lineageRef={input.lineage_ref}
            />
          </div>
        ))}
      </td>
      <td className="py-1.5 text-stone-500 max-w-[12rem]">
        {evaluation.citation && (
          <span title={evaluation.citation}>
            <span className="mr-1 rounded bg-indigo-100 px-1 text-[10px] font-bold text-indigo-700">
              STATE
            </span>
            {evaluation.citation}
          </span>
        )}
      </td>
    </tr>
  );
}

export function AusCard({ detail }: { detail: LoanDetail }) {
  const aus = detail.aus;
  if (!aus)
    return <p className="text-sm text-stone-500">Run underwriting first.</p>;
  const grouped: Record<string, typeof aus.messages> = { PTA: [], PTD: [], PTF: [] };
  for (const message of aus.messages) grouped[message.category].push(message);
  return (
    <Card title={`AUS findings — ${aus.simulator_version} (advisory)`}>
      <p className="mb-2 text-lg font-bold" data-testid="aus-recommendation">
        {aus.recommendation}
        <span className="ml-2 text-sm font-normal text-stone-500">
          {aus.total_points} risk points
        </span>
      </p>
      <div className="mb-3 flex flex-wrap gap-1 text-[10px]">
        {Object.entries(aus.breakdown).map(([factor, points]) => (
          <span key={factor} className="rounded bg-stone-100 px-1.5 py-0.5">
            {factor}: {points}
          </span>
        ))}
      </div>
      {(["PTA", "PTD", "PTF"] as const).map(
        (category) =>
          grouped[category].length > 0 && (
            <div key={category} className="mb-2">
              <h4 className="text-xs font-bold text-stone-500">{category}</h4>
              <ul className="ml-4 list-disc text-sm">
                {grouped[category].map((message) => (
                  <li key={message.message_id}>
                    <span className="font-mono text-xs text-stone-400">
                      {message.message_id}
                    </span>{" "}
                    {message.text}
                  </li>
                ))}
              </ul>
            </div>
          ),
      )}
    </Card>
  );
}

export function ConditionsBoard({ detail }: { detail: LoanDetail }) {
  if (!detail.conditions.length)
    return <p className="text-sm text-stone-500">No conditions yet.</p>;
  const grouped: Record<string, any[]> = { PTA: [], PTD: [], PTF: [] };
  for (const condition of detail.conditions)
    grouped[condition.category]?.push(condition);
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3" data-testid="conditions">
      {(["PTA", "PTD", "PTF"] as const).map((category) => (
        <Card key={category} title={`${category} (${grouped[category].length})`}>
          <ul className="space-y-2">
            {grouped[category].map((condition) => (
              <li
                key={condition.id}
                className="rounded border border-stone-200 p-2 text-sm"
              >
                <div className="font-semibold">{condition.title}</div>
                <div className="text-stone-600">{condition.text}</div>
                <div className="mt-1 text-[10px] text-stone-400">
                  source: {condition.source_kind} / {condition.source_id}
                  {condition.source_kind === "state_rule" && (
                    <span className="ml-1 rounded bg-indigo-100 px-1 font-bold text-indigo-700">
                      STATE REQUIREMENT
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}

export function RedFlagsPanel({ detail }: { detail: LoanDetail }) {
  if (!detail.red_flags.length)
    return (
      <p className="text-sm text-emerald-700" data-testid="red-flags-none">
        No red flags raised.
      </p>
    );
  return (
    <div className="space-y-2" data-testid="red-flags">
      {detail.red_flags
        .sort((a: any, b: any) =>
          a.severity === "critical" ? -1 : b.severity === "critical" ? 1 : 0,
        )
        .map((flag: any) => (
          <div
            key={flag.flag_code + flag.evidence_ref}
            className={`rounded-lg border p-3 ${
              flag.severity === "critical"
                ? "border-red-300 bg-red-50"
                : "border-amber-200 bg-amber-50"
            }`}
          >
            <span
              className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-bold ${SEVERITY_CHIP[flag.severity]}`}
            >
              {flag.severity.toUpperCase()}
            </span>
            <span className="font-mono text-xs font-bold">{flag.flag_code}</span>
            <p className="mt-1 text-sm">{flag.description}</p>
            <p className="text-xs text-stone-500">
              recommended: {flag.recommended_action}
            </p>
          </div>
        ))}
    </div>
  );
}
