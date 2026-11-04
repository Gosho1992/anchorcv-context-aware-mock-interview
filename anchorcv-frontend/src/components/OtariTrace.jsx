// Shows what Mozilla.ai's Otari gateway reported for AnchorCV's AI calls:
// the open-weight model that served each step, whether a fallback fired,
// the integrity guardrail verdict, and the cost.

const TASK_LABELS = {
  interview_questions: "Question generation",
  interview_evaluate: "Answer evaluation",
  interview_teach: "Coaching",
  interview_report: "Readiness report",
  import_job: "Job page import (web fetch)",
  company_research: "Company research (web search)",
  integrity_guardrail: "Integrity check",
};

const ROLE_LABELS = { fast: "fast role", strong: "strong role", guard: "guard role" };

function shortModel(name) {
  if (!name) {
    return "";
  }
  return String(name).replace(/^openai[./]/, "").replace(/^[a-z-]+\//, "");
}

function formatCost(value) {
  const n = Number(value || 0);
  if (!n) {
    return "$0";
  }
  return n < 0.01 ? `$${n.toFixed(5)}` : `$${n.toFixed(3)}`;
}

function guardrailVerdict(call) {
  if (!call?.guardrail) {
    return null;
  }
  if (call.guardrail_skipped) {
    return { label: "Integrity check skipped", tone: "muted" };
  }
  try {
    const entries = JSON.parse(call.guardrails || "[]");
    const entry = Array.isArray(entries) ? entries[0] : null;
    if (!entry) {
      return { label: "Integrity check ran", tone: "ok" };
    }
    if (entry.valid === false) {
      return { label: "Integrity check flagged", tone: "warn" };
    }
    if (entry.status === "unavailable") {
      return { label: "Integrity check skipped", tone: "muted" };
    }
    return { label: "Integrity check passed", tone: "ok" };
  } catch {
    return { label: "Integrity check ran", tone: "ok" };
  }
}

const chipStyle = {
  display: "inline-flex",
  alignItems: "center",
  gap: "0.3rem",
  padding: "0.15rem 0.55rem",
  borderRadius: "999px",
  fontSize: "0.78rem",
  border: "1px solid rgba(148,163,184,0.35)",
  whiteSpace: "nowrap",
};

const toneColor = {
  ok: "rgba(20,184,166,0.55)",
  warn: "rgba(245,158,11,0.65)",
  muted: "rgba(148,163,184,0.35)",
};

function Chip({ children, tone = "muted", title }) {
  return (
    <span style={{ ...chipStyle, borderColor: toneColor[tone] || toneColor.muted }} title={title}>
      {children}
    </span>
  );
}

/** One response's trace, e.g. under an evaluated answer. */
export function OtariTraceLine({ otari }) {
  const calls = (otari?.calls || []).filter((call) => call.provider === "otari" && call.ok);
  if (!calls.length) {
    return null;
  }
  return (
    <div className="button-row" style={{ justifyContent: "flex-start", flexWrap: "wrap", gap: "0.4rem" }}>
      {calls.map((call, index) => {
        const verdict = guardrailVerdict(call);
        return (
          <span key={`${call.request_id || index}`} style={{ display: "contents" }}>
            <Chip title={`${TASK_LABELS[call.task] || call.task || "AI step"} · ${ROLE_LABELS[call.role] || call.role} · Otari target ${call.target}`}>
              ⚙ {shortModel(call.served_model) || call.target} via Otari
            </Chip>
            {call.fallback ? <Chip tone="warn" title="The main model failed; Otari's routing policy served this from the backup model.">↪ fallback used</Chip> : null}
            {verdict ? <Chip tone={verdict.tone}>🛡 {verdict.label}</Chip> : null}
            {(call.tool_calls || []).length ? (
              <Chip title={(call.tool_calls || []).map((t) => t.url || t.query || t.type).join("\n")}>
                🌐 {(call.tool_calls || []).length} web {(call.tool_calls || []).length === 1 ? "call" : "calls"}
              </Chip>
            ) : null}
            <Chip>{formatCost(call.cost_usd)}</Chip>
          </span>
        );
      })}
    </div>
  );
}

/** Whole-interview summary for the report. */
export function OtariTraceSummary({ calls }) {
  const otariCalls = (calls || []).filter((call) => call.provider === "otari");
  if (!otariCalls.length) {
    return null;
  }

  const rows = new Map();
  for (const call of otariCalls) {
    const key = call.task || "other";
    const row = rows.get(key) || { task: key, models: new Set(), count: 0, fallbacks: 0, cost: 0, failed: 0, ms: 0 };
    row.count += 1;
    if (call.ok) {
      row.models.add(shortModel(call.served_model) || call.target);
      row.cost += Number(call.cost_usd || 0);
      row.ms += Number(call.latency_ms || 0);
    } else {
      row.failed += 1;
    }
    if (call.fallback) {
      row.fallbacks += 1;
    }
    rows.set(key, row);
  }

  const totalCost = otariCalls.reduce((sum, call) => sum + Number(call.cost_usd || 0), 0);
  const fallbacks = otariCalls.filter((call) => call.fallback).length;
  const guarded = otariCalls.filter((call) => call.guardrail).length;
  const models = new Set(otariCalls.filter((c) => c.ok).map((c) => shortModel(c.served_model) || c.target));
  const budget = [...otariCalls].reverse().find((c) => c.end_user_budget)?.end_user_budget;

  return (
    <details className="analysis-meta-card">
      <summary style={{ cursor: "pointer", fontWeight: 700 }}>
        How this interview was powered — {models.size} open-weight {models.size === 1 ? "model" : "models"} via Mozilla.ai Otari · {formatCost(totalCost)} total
      </summary>
      <div className="stack tight" style={{ marginTop: "0.7rem" }}>
        <div className="button-row" style={{ justifyContent: "flex-start", flexWrap: "wrap", gap: "0.4rem" }}>
          <Chip tone="ok">{otariCalls.length} AI calls</Chip>
          <Chip tone={fallbacks ? "warn" : "muted"}>{fallbacks} fallbacks</Chip>
          <Chip tone="ok">🛡 {guarded} integrity checks</Chip>
          {budget ? <Chip title="Your AnchorCV plan's AI allowance in Otari">Budget: {budget}</Chip> : null}
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr style={{ textAlign: "left" }}>
                <th style={{ padding: "0.3rem 0.4rem" }}>Step</th>
                <th style={{ padding: "0.3rem 0.4rem" }}>Model(s) that served it</th>
                <th style={{ padding: "0.3rem 0.4rem" }}>Calls</th>
                <th style={{ padding: "0.3rem 0.4rem" }}>Fallbacks</th>
                <th style={{ padding: "0.3rem 0.4rem" }}>Avg time</th>
                <th style={{ padding: "0.3rem 0.4rem" }}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {[...rows.values()].map((row) => (
                <tr key={row.task} style={{ borderTop: "1px solid rgba(148,163,184,0.2)" }}>
                  <td style={{ padding: "0.3rem 0.4rem" }}>{TASK_LABELS[row.task] || row.task}</td>
                  <td style={{ padding: "0.3rem 0.4rem" }}>{[...row.models].join(", ") || "—"}</td>
                  <td style={{ padding: "0.3rem 0.4rem" }}>{row.count}{row.failed ? ` (${row.failed} refused)` : ""}</td>
                  <td style={{ padding: "0.3rem 0.4rem" }}>{row.fallbacks}</td>
                  <td style={{ padding: "0.3rem 0.4rem" }}>{row.count - row.failed ? `${((row.ms / (row.count - row.failed)) / 1000).toFixed(1)}s` : "—"}</td>
                  <td style={{ padding: "0.3rem 0.4rem" }}>{formatCost(row.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="subtle-copy" style={{ margin: 0 }}>
          Every AI step ran on open-weight models through Otari, Mozilla.ai's open-source AI gateway, with routing
          fallbacks, a per-user budget and AnchorCV's integrity guardrail.
        </p>
      </div>
    </details>
  );
}

export default OtariTraceLine;
