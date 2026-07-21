const OUTPUT_OPTIONS = [
  {
    value: "Application_Strategy",
    title: "Application Strategy",
    badge: "PLAN",
    description: "Analyze fit, gaps, and build an action plan.",
  },
  {
    value: "ATS_Optimization",
    title: "ATS Score & Keywords",
    badge: "ATS",
    description: "Check if your CV passes automated screening.",
  },
  {
    value: "Resume_Optimization",
    title: "Resume Improvement",
    badge: "CV",
    description: "Rewrite weak bullets with metrics and action verbs.",
  },
  {
    value: "Job_Match_Score",
    title: "Job Match Score",
    badge: "MATCH",
    description: "See your match percentage across skills and keywords.",
  },
  {
    value: "Cover_Letter",
    title: "Cover Letter",
    badge: "LETTER",
    description: "Generate a personalized letter that sounds like you.",
  },
  {
    value: "Email_Template",
    title: "Email to Professor",
    badge: "EMAIL",
    description: "Write a cold email professors actually read.",
  },
];

export default function OutputTypeCards({
  selectedOutputs = [],
  onToggle,
  lockedOutputs = [],
  onAttemptLocked,
}) {
  return (
    <div className="analysis-option-grid">
      {OUTPUT_OPTIONS.map((option) => (
        (() => {
          const isLocked = lockedOutputs.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              className={`analysis-option-card ${
                selectedOutputs.includes(option.value) ? "selected" : ""
              } ${isLocked ? "locked" : ""}`}
              onClick={() => {
                if (isLocked) {
                  onAttemptLocked?.(option.value);
                  return;
                }
                onToggle?.(option.value);
              }}
              aria-disabled={isLocked}
              title={isLocked ? "Premium output - upgrade required" : undefined}
            >
              <span className="analysis-option-badge">{option.badge}</span>
              <strong>{option.title}</strong>
              <span className="muted-copy">{option.description}</span>
              {isLocked ? (
                <span className="muted-copy" style={{ fontSize: "0.78rem", color: "#f59e0b" }}>
                  Premium output
                </span>
              ) : null}
            </button>
          );
        })()
      ))}
    </div>
  );
}
