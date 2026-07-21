const INTENT_LABELS = {
  job: {
    proximityTitle: "In-demand roles",
    proximityHint: "Longer bar means closer to job readiness. Teal indicates fast growth.",
    adjacentTitle: "Adjacent fields (some upskilling needed)",
    opportunitiesTitle: "Programmes and opportunities",
    opportunitiesDesc: "Curated international programmes. Verify each entry on the official site before applying.",
    regionalTitle: "Where the jobs are",
    gapTitle: "Your job-readiness analysis",
    analyzeLabel: "Tailor my CV ->",
    salaryLabel: "Salary insights",
  },
  phd: {
    proximityTitle: "PhD research areas",
    proximityHint: "Longer bar means stronger research fit with your background. Teal indicates actively funded domains.",
    adjacentTitle: "Adjacent research domains",
    opportunitiesTitle: "PhD funding and programmes",
    opportunitiesDesc: "Verified doctoral funding from international schemes. Confirm deadlines on the official site.",
    regionalTitle: "Where to find funded positions",
    gapTitle: "PhD application readiness",
    analyzeLabel: "Check my CV fit ->",
    salaryLabel: "PhD stipend ranges",
  },
  masters: {
    proximityTitle: "Master's specialisations",
    proximityHint: "Longer bar means stronger fit to your undergraduate background.",
    adjacentTitle: "Adjacent disciplines",
    opportunitiesTitle: "Scholarships and Master's programmes",
    opportunitiesDesc: "Verified funding and programme options. Confirm deadlines on the official site.",
    regionalTitle: "Best countries to study",
    gapTitle: "Master's application readiness",
    analyzeLabel: "Check my CV fit ->",
    salaryLabel: "Graduate salary outlook",
  },
  scholarship: {
    proximityTitle: "Funding tracks",
    proximityHint: "Longer bar means stronger eligibility match for this type of award.",
    adjacentTitle: "Related funding categories",
    opportunitiesTitle: "Scholarships and fellowships",
    opportunitiesDesc: "Verified awards from the allowlist. Confirm details on official sites.",
    regionalTitle: "Where funding is strongest",
    gapTitle: "Scholarship application readiness",
    analyzeLabel: "Check my CV fit ->",
    salaryLabel: "Typical stipend amounts",
  },
  bachelors: {
    proximityTitle: "Bachelor's programme tracks",
    proximityHint: "Longer bar means stronger admission readiness based on your background.",
    adjacentTitle: "Adjacent undergraduate paths",
    opportunitiesTitle: "Scholarships and programmes",
    opportunitiesDesc: "Funding options for undergraduate study. Verify requirements and deadlines officially.",
    regionalTitle: "Best countries for undergraduates",
    gapTitle: "Undergraduate application readiness",
    analyzeLabel: "Check my CV fit ->",
    salaryLabel: "Tuition and stipend ranges",
  },
};

const IMPORTANCE_COLOR = {
  essential: { bg: "rgba(239,68,68,0.12)", text: "#fca5a5" },
  helpful: { bg: "rgba(245,158,11,0.12)", text: "#fcd34d" },
  "nice-to-have": { bg: "rgba(100,116,139,0.12)", text: "#94a3b8" },
};

function getIntentLabels(intent) {
  return INTENT_LABELS[intent] || INTENT_LABELS.job;
}

function distanceToReadiness(dist = "") {
  const value = String(dist).toLowerCase();
  if (value === "close") return 90;
  if (value.includes("week") || value.includes("4-8")) return 62;
  if (value.includes("month") || value.includes("3-6")) return 33;
  if (value.includes("shift")) return 12;
  return 45;
}

function fitColor(score) {
  if (score >= 75) return "var(--accent-teal, #2dd4a8)";
  if (score >= 50) return "var(--accent)";
  if (score >= 30) return "#f59e0b";
  return "#ef4444";
}

function demandBadge(level) {
  if (level === "high") return { color: "rgba(239,68,68,0.15)", text: "#fca5a5", label: "High demand" };
  if (level === "medium") return { color: "rgba(99,102,241,0.15)", text: "#a5b4fc", label: "Moderate" };
  return { color: "rgba(100,116,139,0.15)", text: "#94a3b8", label: "Low demand" };
}

function GapAnalysisSection({ ga }) {
  const scoreColor = fitColor(ga.fit_score || 0);
  const fitLabels = { strong: "Strong fit", good: "Good fit", partial: "Partial fit", stretch: "Stretch" };
  const fitBg = {
    strong: "rgba(45,212,168,0.15)",
    good: "rgba(99,102,241,0.15)",
    partial: "rgba(245,158,11,0.12)",
    stretch: "rgba(239,68,68,0.12)",
  };
  const fitText = {
    strong: "#2dd4a8",
    good: "#a5b4fc",
    partial: "#fcd34d",
    stretch: "#fca5a5",
  };

  return (
    <div className="stack tight">
      <div style={{ display: "flex", alignItems: "center", gap: "1.25rem", flexWrap: "wrap" }}>
        <div style={{ textAlign: "center", flexShrink: 0 }}>
          <div style={{
            width: "72px", height: "72px", borderRadius: "50%",
            background: `conic-gradient(${scoreColor} ${(ga.fit_score || 0) * 3.6}deg, rgba(255,255,255,0.06) 0deg)`,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <div style={{
              width: "54px", height: "54px", borderRadius: "50%",
              background: "var(--surface)", display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
            }}>
              <span style={{ fontSize: "1.05rem", fontWeight: 700, color: scoreColor, lineHeight: 1 }}>{ga.fit_score}</span>
              <span style={{ fontSize: "0.6rem", color: "var(--text-secondary)", lineHeight: 1 }}>/100</span>
            </div>
          </div>
        </div>
        <div>
          <span style={{
            display: "inline-block", padding: "0.25rem 0.75rem", borderRadius: "999px",
            fontSize: "0.82rem", fontWeight: 700, marginBottom: "0.3rem",
            background: fitBg[ga.overall_fit] || "rgba(99,102,241,0.15)",
            color: fitText[ga.overall_fit] || "#a5b4fc",
          }}>
            {fitLabels[ga.overall_fit] || ga.overall_fit}
          </span>
          <p className="muted-copy" style={{ margin: 0, fontSize: "0.82rem" }}>
            Ready in: <strong style={{ color: "var(--text-primary)" }}>{ga.time_to_readiness}</strong>
          </p>
        </div>
      </div>

      <p style={{ margin: 0, fontSize: "0.88rem", lineHeight: 1.6 }}>{ga.recommendation}</p>

      {ga.strengths?.length > 0 && (
        <div>
          <p className="muted-copy" style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", fontWeight: 600 }}>Your strengths</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
            {ga.strengths.map((strength, index) => (
              <span key={index} style={{ fontSize: "0.8rem", padding: "0.2rem 0.6rem", borderRadius: "999px", background: "rgba(45,212,168,0.1)", color: "#2dd4a8" }}>
                {strength}
              </span>
            ))}
          </div>
        </div>
      )}

      {ga.gaps?.length > 0 && (
        <div>
          <p className="muted-copy" style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", fontWeight: 600 }}>Gaps to close</p>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem" }}>
            {ga.gaps.map((gap, index) => {
              const ic = IMPORTANCE_COLOR[gap.importance] || IMPORTANCE_COLOR["nice-to-have"];
              return (
                <div key={index} style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem", flexWrap: "wrap" }}>
                  <span style={{
                    flexShrink: 0, fontSize: "0.75rem", padding: "0.18rem 0.5rem",
                    borderRadius: "999px", background: ic.bg, color: ic.text, fontWeight: 600, whiteSpace: "nowrap",
                  }}>
                    {gap.importance}
                  </span>
                  <div style={{ flex: 1, minWidth: "140px" }}>
                    <span style={{ fontWeight: 600, fontSize: "0.88rem" }}>{gap.skill}</span>
                    <span className="muted-copy" style={{ fontSize: "0.8rem" }}> - {gap.time_to_acquire}</span>
                    {gap.resources?.length > 0 && (
                      <p className="muted-copy" style={{ margin: "0.15rem 0 0", fontSize: "0.76rem" }}>
                        Resources: {gap.resources.join(", ")}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default function DiscoveryLandscape({
  displayedLandscape,
  isSample,
  loading,
  onRegenerate,
  onAnalyzeOpportunity,
  onUseSearchTag,
  onCopyAllTags,
}) {
  if (!displayedLandscape) {
    return null;
  }

  const IL = getIntentLabels(displayedLandscape?.intent || "job");

  return (
    <>
      <div className="panel stack tight">
        <strong style={{ fontSize: "1rem" }}>{displayedLandscape.primary_field}</strong>
        <p style={{ fontSize: "1rem", lineHeight: 1.65, margin: 0 }}>{displayedLandscape.summary}</p>
        {displayedLandscape.salary_insights && (
          <p className="muted-copy" style={{ margin: 0, fontSize: "0.88rem" }}>
            {IL.salaryLabel}: {displayedLandscape.salary_insights}
          </p>
        )}
        {!isSample && (
          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <button className="secondary-button compact-button" onClick={onRegenerate} disabled={loading}>
              {loading ? "Regenerating..." : "Regenerate"}
            </button>
            {displayedLandscape.cached && (
              <span className="muted-copy" style={{ fontSize: "0.82rem" }}>Loaded from cache</span>
            )}
          </div>
        )}
      </div>

      {displayedLandscape.related_subfields?.length > 0 && (
        <div className="panel stack">
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem", flexWrap: "wrap" }}>
            <h3 style={{ margin: 0 }}>{IL.proximityTitle}</h3>
            <span className="muted-copy" style={{ fontSize: "0.8rem" }}>{IL.proximityHint}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
            {displayedLandscape.related_subfields.map((field, index) => {
              const pct = distanceToReadiness(field.distance_from_user);
              const isGrowing = field.growing;
              const barColor = isGrowing
                ? "linear-gradient(90deg, rgba(45,212,168,0.9), rgba(45,212,168,0.5))"
                : "linear-gradient(90deg, rgba(124,111,247,0.8), rgba(124,111,247,0.4))";
              return (
                <div key={`prox-${index}`}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem", gap: "0.5rem", flexWrap: "wrap" }}>
                    <span style={{ fontWeight: 600, fontSize: "0.92rem" }}>{field.name}</span>
                    <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                      <span style={{
                        fontSize: "0.75rem", padding: "0.2rem 0.55rem", borderRadius: "999px",
                        background: isGrowing ? "rgba(45,212,168,0.12)" : "rgba(124,111,247,0.12)",
                        color: isGrowing ? "#2dd4a8" : "var(--accent-soft)",
                        fontWeight: 600,
                      }}>
                        {isGrowing ? "Growing" : "Stable"}
                      </span>
                      <span className="muted-copy" style={{ fontSize: "0.78rem" }}>{field.distance_from_user}</span>
                    </div>
                  </div>
                  <div style={{ height: "10px", borderRadius: "999px", background: "rgba(255,255,255,0.06)", overflow: "hidden" }}>
                    <div style={{
                      width: `${pct}%`, height: "100%",
                      background: barColor,
                      borderRadius: "999px",
                      transition: "width 0.6s ease",
                    }} />
                  </div>
                  <p className="muted-copy" style={{ margin: "0.3rem 0 0", fontSize: "0.8rem" }}>{field.why}</p>
                  {field.typical_roles?.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", marginTop: "0.3rem" }}>
                      {field.typical_roles.map((role) => (
                        <span key={role} className="quota-pill" style={{ fontSize: "0.75rem" }}>{role}</span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {displayedLandscape.gap_analysis && (
        <div className="panel stack">
          <h3 style={{ margin: 0 }}>{IL.gapTitle}</h3>
          <GapAnalysisSection ga={displayedLandscape.gap_analysis} />
        </div>
      )}

      {displayedLandscape.regional_demand?.length > 0 && (
        <div className="stack tight">
          <h3 style={{ margin: 0 }}>{IL.regionalTitle}</h3>
          <div className="grid two-up">
            {displayedLandscape.regional_demand.map((rd, index) => {
              const badge = demandBadge(rd.demand_level);
              return (
                <div key={`rd-${index}`} className="panel stack tight" style={{ gap: "0.55rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
                    <strong style={{ fontSize: "0.95rem" }}>{rd.region}</strong>
                    <span style={{
                      fontSize: "0.75rem", padding: "0.22rem 0.6rem", borderRadius: "999px",
                      background: badge.color, color: badge.text, fontWeight: 600,
                    }}>
                      {badge.label}
                    </span>
                  </div>
                  {rd.typical_salary && (
                    <span className="muted-copy" style={{ fontSize: "0.82rem", fontWeight: 600 }}>
                      {rd.typical_salary}
                    </span>
                  )}
                  <p className="muted-copy" style={{ margin: 0, fontSize: "0.82rem" }}>{rd.notes}</p>
                  {rd.trending && (
                    <span style={{ fontSize: "0.76rem", color: "#2dd4a8", fontWeight: 600 }}>Trending upward</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {displayedLandscape.learning_paths?.length > 0 && (
        <div className="stack tight">
          <h3 style={{ margin: 0 }}>How to prepare</h3>
          {displayedLandscape.learning_paths.map((lp, index) => (
            <div key={`lp-${index}`} className="panel stack tight">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem", flexWrap: "wrap" }}>
                <strong style={{ fontSize: "0.95rem" }}>{lp.title}</strong>
                <span className="quota-pill">{lp.duration}</span>
              </div>
              <p className="muted-copy" style={{ margin: 0, fontSize: "0.82rem" }}>Outcome: {lp.outcome}</p>
              <ol style={{ margin: "0.35rem 0 0", paddingLeft: "1.25rem", display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                {lp.steps.map((step, stepIndex) => (
                  <li key={stepIndex} style={{ fontSize: "0.88rem", lineHeight: 1.55 }}>{step}</li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      )}

      {displayedLandscape.adjacent_fields?.length > 0 && (
        <div className="stack tight">
          <h3 style={{ margin: 0 }}>{IL.adjacentTitle}</h3>
          <div className="grid two-up">
            {displayedLandscape.adjacent_fields.map((field, index) => (
              <div key={`adj-${index}`} className="panel stack tight" style={{ opacity: 0.88 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
                  <strong>{field.name}</strong>
                  <span className="muted-copy" style={{ fontSize: "0.78rem" }}>{field.distance_from_user}</span>
                </div>
                <p className="muted-copy" style={{ margin: 0 }}>{field.description}</p>
                <p className="muted-copy" style={{ margin: 0, fontSize: "0.82rem" }}>{field.why}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {displayedLandscape.known_opportunities?.length > 0 && (
        <div className="stack tight">
          <h3 style={{ margin: 0 }}>{IL.opportunitiesTitle}</h3>
          <p className="muted-copy" style={{ margin: 0 }}>{IL.opportunitiesDesc}</p>
          <div className="grid two-up">
            {displayedLandscape.known_opportunities.map((opp, index) => (
              <div key={`opp-${index}`} className="panel stack tight">
                <strong>{opp.title}</strong>
                <p className="muted-copy" style={{ margin: 0 }}>
                  {opp.institution}, {opp.country} - {opp.type}
                </p>
                {opp.note && <p className="muted-copy" style={{ margin: 0 }}>{opp.note}</p>}
                <button
                  className="primary-button compact-button"
                  onClick={() => onAnalyzeOpportunity(opp)}
                  disabled={isSample}
                >
                  {IL.analyzeLabel}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {displayedLandscape.search_tags?.length > 0 && (
        <div className="panel stack">
          <div className="discover-footer-row">
            <strong>Search tags</strong>
            <button className="secondary-button compact-button" onClick={onCopyAllTags} disabled={isSample}>
              Copy all
            </button>
          </div>
          <p className="muted-copy" style={{ margin: 0 }}>
            Use these on Google, EURAXESS, or directly on university sites.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            {displayedLandscape.search_tags.map((tag, index) => (
              <button
                key={`tag-${index}`}
                className="tag-button"
                onClick={() => (!isSample ? onUseSearchTag(tag) : null)}
                disabled={isSample}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
