// Extracted from TemplatesPage.jsx so the template gallery (cards) and the
// selected-template detail (section structure + reviewer expectations) can be
// reused by the Canvas templates flow. TemplatesPage.jsx imports these too.

export default function TemplateGallery({ templates = [], selectedId, onSelect }) {
  return (
          <div
            className="card-grid"
            style={{ gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))" }}
          >
            {templates.map((template, index) => (
              <button
                key={template.id}
                type="button"
                className={`panel-interactive stack tight card-enter-${Math.min(index + 1, 6)}`}
                onClick={() => onSelect && onSelect(template.id)}
                aria-pressed={selectedId === template.id}
                style={{
                  alignItems: "flex-start",
                  textAlign: "left",
                  borderColor:
                    selectedId === template.id
                      ? "color-mix(in srgb, var(--accent) 60%, var(--border))"
                      : undefined,
                  boxShadow: selectedId === template.id ? "var(--shadow-glow-accent)" : undefined,
                }}
              >
                <p className="eyebrow" style={{ margin: 0 }}>
                  {selectedId === template.id ? "Selected" : "Template"}
                </p>
                <strong>{template.name}</strong>
                <span className="muted-copy">{template.tagline}</span>
              </button>
            ))}
          </div>
  );
}

export function TemplateDetail({ template: selectedTemplate }) {
  if (!selectedTemplate) return null;
  return (
    <>
            <div className="stack tight">
              <p className="eyebrow">{selectedTemplate.name}</p>
              <p className="muted-copy" style={{ margin: 0 }}>
                <strong>Best for:</strong> {selectedTemplate.audience}
              </p>
            </div>

            <div
              className="card-grid"
              style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}
            >
              <div className="analysis-meta-card">
                <p style={{ margin: "0 0 0.5rem", fontWeight: 700 }}>Section structure</p>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(selectedTemplate.sections || []).map((section) => (
                    <li key={section} className="muted-copy" style={{ marginBottom: "0.3rem" }}>
                      {section}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="analysis-meta-card teal">
                <p style={{ margin: "0 0 0.5rem", fontWeight: 700 }}>What reviewers expect</p>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(selectedTemplate.standards || []).map((standard) => (
                    <li key={standard} className="muted-copy" style={{ marginBottom: "0.3rem" }}>
                      {standard}
                    </li>
                  ))}
                </ul>
                <p className="subtle-copy" style={{ margin: "0.6rem 0 0", fontSize: "0.82rem" }}>
                  {selectedTemplate.example_note}
                </p>
              </div>
            </div>
    </>
  );
}
