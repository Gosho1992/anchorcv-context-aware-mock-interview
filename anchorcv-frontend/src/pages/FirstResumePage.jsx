import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useEffect, useMemo, useState } from "react";
import { postJson } from "../api/client";

const DRAFT_KEY = "anchorcv-first-resume-draft";

const baseSections = [
  { id: "summary", title: "Professional Summary" },
  { id: "education", title: "Education" },
  { id: "experience", title: "Experience" },
  { id: "skills", title: "Skills" },
  { id: "projects", title: "Projects" },
];

const customOptions = [
  "Certifications",
  "Awards",
  "Publications",
  "Volunteer Work",
  "Languages",
  "References",
  "Conferences",
  "Custom name",
];

const templateOptions = [
  { label: "ATS", value: "ATS" },
  { label: "Europass", value: "Europass" },
  { label: "Academic", value: "Academic" },
  { label: "One-Page", value: "One-Page" },
];

function emptyEducation() {
  return { degree: "", institution: "", start_date: "", end_date: "", gpa: "", coursework: "" };
}

function emptyExperience() {
  return { title: "", company: "", start_date: "", end_date: "", current: false, bullets: "" };
}

function emptyProject() {
  return { name: "", description: "", technologies: "", link: "" };
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function buildFirstResumeFilename(extension) {
  return `anchorcv-first-resume${extension}`;
}

function defaultDraft() {
  return {
    format: "ATS",
    enhance: true,
    openSections: {
      summary: true,
      education: true,
      experience: true,
      skills: true,
      projects: true,
    },
    sectionOrder: baseSections.map((section) => section.id),
    formData: {
      personal: { name: "", email: "", phone: "", location: "", linkedin: "" },
      sections: {
        summary: "",
        education: [emptyEducation()],
        experience: [emptyExperience()],
        skills: "",
        projects: [emptyProject()],
        custom_sections: [],
      },
    },
  };
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function hasText(value) {
  if (Array.isArray(value)) return value.some(hasText);
  if (value && typeof value === "object") return Object.values(value).some(hasText);
  return Boolean(String(value || "").trim());
}

function makeLocalPreview(formData, order) {
  const personal = formData.personal || {};
  const sections = formData.sections || {};
  const rows = [];
  const sectionHtml = {
    summary: sections.summary
      ? `<section><h2>Professional Summary</h2><p>${escapeHtml(sections.summary)}</p></section>`
      : "",
    education: (sections.education || []).filter(hasText).length
      ? `<section><h2>Education</h2>${(sections.education || [])
          .filter(hasText)
          .map(
            (item) => `<div class="item"><strong>${escapeHtml(item.degree)}</strong><br>${escapeHtml(
              item.institution
            )}<br><span>${escapeHtml([item.start_date, item.end_date].filter(Boolean).join(" - "))}</span>${
              item.gpa ? `<p>GPA: ${escapeHtml(item.gpa)}</p>` : ""
            }${item.coursework ? `<p>${escapeHtml(item.coursework)}</p>` : ""}</div>`
          )
          .join("")}</section>`
      : "",
    experience: (sections.experience || []).filter(hasText).length
      ? `<section><h2>Experience</h2>${(sections.experience || [])
          .filter(hasText)
          .map((item) => {
            const bullets = String(item.bullets || "")
              .split("\n")
              .filter(Boolean)
              .map((line) => `<li>${escapeHtml(line)}</li>`)
              .join("");
            return `<div class="item"><strong>${escapeHtml(item.title)}</strong><br>${escapeHtml(
              item.company
            )}<br><span>${escapeHtml([item.start_date, item.current ? "Present" : item.end_date].filter(Boolean).join(" - "))}</span>${
              bullets ? `<ul>${bullets}</ul>` : ""
            }</div>`;
          })
          .join("")}</section>`
      : "",
    skills: sections.skills
      ? `<section><h2>Skills</h2><p>${escapeHtml(sections.skills)}</p></section>`
      : "",
    projects: (sections.projects || []).filter(hasText).length
      ? `<section><h2>Projects</h2>${(sections.projects || [])
          .filter(hasText)
          .map(
            (item) => `<div class="item"><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(
              item.description
            )}</p>${item.technologies ? `<p>${escapeHtml(item.technologies)}</p>` : ""}${
              item.link ? `<p>${escapeHtml(item.link)}</p>` : ""
            }</div>`
          )
          .join("")}</section>`
      : "",
  };

  rows.push(...order.map((id) => sectionHtml[id]).filter(Boolean));
  rows.push(
    ...(sections.custom_sections || [])
      .filter((section) => String(section.content || "").trim())
      .map(
        (section) =>
          `<section><h2>${escapeHtml(section.name || section.type)}</h2>${String(section.content || "")
            .split("\n")
            .filter(Boolean)
            .map((line) => `<p>${escapeHtml(line)}</p>`)
            .join("")}</section>`
      )
  );

  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body{font-family:Arial,sans-serif;color:#111827;background:#fff;margin:0;padding:34px;line-height:1.45}
    h1{font-size:30px;margin:0 0 6px;color:#111827} .contact{font-size:13px;color:#4b5563;margin-bottom:24px}
    h2{font-size:13px;letter-spacing:0;text-transform:uppercase;border-bottom:1px solid #d1d5db;padding-bottom:5px;margin:22px 0 10px}
    p{margin:5px 0}.item{margin:0 0 13px}ul{margin:7px 0 0 20px;padding:0}span{color:#4b5563}
  </style></head><body>
    <h1>${escapeHtml(personal.name || "Your Name")}</h1>
    <div class="contact">${escapeHtml([personal.email, personal.phone, personal.location, personal.linkedin].filter(Boolean).join(" | "))}</div>
    ${rows.join("") || "<p>Start filling the form to preview your resume.</p>"}
  </body></html>`;
}

function SortableSection({ id, title, children }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.7 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} className="first-resume-section">
      <div className="first-resume-section-title">
        <button type="button" className="icon-button drag-handle" {...attributes} {...listeners} aria-label={`Move ${title}`}>
          ::
        </button>
        {children}
      </div>
    </div>
  );
}

export default function FirstResumePage() {
  const [draft, setDraft] = useState(defaultDraft);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [generatedHtml, setGeneratedHtml] = useState("");
  const [generatedCvData, setGeneratedCvData] = useState(null);
  const [customChoice, setCustomChoice] = useState("");
  const [exporting, setExporting] = useState("");

  useEffect(() => {
    try {
      const stored = localStorage.getItem(DRAFT_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        setDraft({ ...defaultDraft(), ...parsed });
      }
    } catch {
      setDraft(defaultDraft());
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  }, [draft]);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const previewHtml = useMemo(
    () => generatedHtml || makeLocalPreview(draft.formData, draft.sectionOrder),
    [draft.formData, draft.sectionOrder, generatedHtml]
  );

  function updateDraft(updater) {
    setGeneratedHtml("");
    setGeneratedCvData(null);
    setDraft((current) => (typeof updater === "function" ? updater(current) : updater));
  }

  function updatePersonal(field, value) {
    updateDraft((current) => ({
      ...current,
      formData: {
        ...current.formData,
        personal: { ...current.formData.personal, [field]: value },
      },
    }));
  }

  function updateSection(field, value) {
    updateDraft((current) => ({
      ...current,
      formData: {
        ...current.formData,
        sections: { ...current.formData.sections, [field]: value },
      },
    }));
  }

  function updateList(section, index, field, value) {
    updateDraft((current) => {
      const nextList = [...(current.formData.sections[section] || [])];
      nextList[index] = { ...nextList[index], [field]: value };
      return {
        ...current,
        formData: {
          ...current.formData,
          sections: { ...current.formData.sections, [section]: nextList },
        },
      };
    });
  }

  function addListItem(section) {
    const factories = { education: emptyEducation, experience: emptyExperience, projects: emptyProject };
    updateSection(section, [...(draft.formData.sections[section] || []), factories[section]()]);
  }

  function removeListItem(section, index) {
    updateSection(
      section,
      (draft.formData.sections[section] || []).filter((_, itemIndex) => itemIndex !== index)
    );
  }

  function toggleSection(id) {
    updateDraft((current) => ({
      ...current,
      openSections: { ...current.openSections, [id]: !current.openSections[id] },
    }));
  }

  function moveSection(id, direction) {
    const index = draft.sectionOrder.indexOf(id);
    const nextIndex = index + direction;
    if (index < 0 || nextIndex < 0 || nextIndex >= draft.sectionOrder.length) return;
    updateDraft((current) => ({ ...current, sectionOrder: arrayMove(current.sectionOrder, index, nextIndex) }));
  }

  function handleDragEnd(event) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    updateDraft((current) => {
      const oldIndex = current.sectionOrder.indexOf(active.id);
      const newIndex = current.sectionOrder.indexOf(over.id);
      return { ...current, sectionOrder: arrayMove(current.sectionOrder, oldIndex, newIndex) };
    });
  }

  function addCustomSection() {
    if (!customChoice) return;
    const name = customChoice === "Custom name" ? "Custom Section" : customChoice;
    const id = `custom_${Date.now()}`;
    updateDraft((current) => ({
      ...current,
      openSections: { ...current.openSections, [id]: true },
      sectionOrder: [...current.sectionOrder, id],
      formData: {
        ...current.formData,
        sections: {
          ...current.formData.sections,
          custom_sections: [...current.formData.sections.custom_sections, { id, type: customChoice, name, content: "" }],
        },
      },
    }));
    setCustomChoice("");
  }

  function updateCustom(id, field, value) {
    updateDraft((current) => ({
      ...current,
      formData: {
        ...current.formData,
        sections: {
          ...current.formData.sections,
          custom_sections: current.formData.sections.custom_sections.map((section) =>
            section.id === id ? { ...section, [field]: value } : section
          ),
        },
      },
    }));
  }

  function removeCustom(id) {
    updateDraft((current) => ({
      ...current,
      sectionOrder: current.sectionOrder.filter((sectionId) => sectionId !== id),
      formData: {
        ...current.formData,
        sections: {
          ...current.formData.sections,
          custom_sections: current.formData.sections.custom_sections.filter((section) => section.id !== id),
        },
      },
    }));
  }

  function saveDraft() {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    setStatus("Draft saved.");
    setError("");
  }

  function clearAll() {
    if (!window.confirm("Clear all First Resume draft data?")) return;
    localStorage.removeItem(DRAFT_KEY);
    setDraft(defaultDraft());
    setGeneratedHtml("");
    setGeneratedCvData(null);
    setStatus("");
    setError("");
  }

  async function generateResume() {
    setStatus("Generating resume...");
    setError("");
    try {
      const result = await postJson("/first-resume/generate", {
        form_data: draft.formData,
        section_order: draft.sectionOrder,
        format: draft.format,
        enhance: draft.enhance,
      });
      setGeneratedHtml(result.html || "");
      setGeneratedCvData(result.cv_data || null);
      setStatus("Resume generated.");
    } catch (err) {
      setError(err.message || "Could not generate resume.");
      setStatus("");
    }
  }

  async function exportResume(type) {
    if (!generatedHtml) return;
    setExporting(type);
    setError("");
    try {
      const extension = type === "docx" ? ".docx" : ".pdf";
      const result = await postJson(`/first-resume/export/${type}`, {
        html: generatedHtml,
        cv_data: type === "docx" ? generatedCvData : undefined,
        filename: buildFirstResumeFilename(extension),
      });
      downloadBlob(result, buildFirstResumeFilename(extension));
    } catch (err) {
      setError(err.message || `Unable to export ${type.toUpperCase()}.`);
    } finally {
      setExporting("");
    }
  }

  function renderSection(id) {
    const title = baseSections.find((section) => section.id === id)?.title;
    const custom = draft.formData.sections.custom_sections.find((section) => section.id === id);
    const label = title || custom?.name || "Custom Section";
    const open = draft.openSections[id] !== false;

    return (
      <section className="first-resume-collapsible" key={id}>
        <div className="first-resume-collapse-head">
          <button type="button" className="link-button" onClick={() => toggleSection(id)}>
            {open ? "▾" : "▸"} {label}
          </button>
          <div className="first-resume-reorder-buttons">
            <button type="button" className="icon-button" onClick={() => moveSection(id, -1)} aria-label={`Move ${label} up`}>
              ▲
            </button>
            <button type="button" className="icon-button" onClick={() => moveSection(id, 1)} aria-label={`Move ${label} down`}>
              ▼
            </button>
          </div>
        </div>
        {open ? <div className="first-resume-fields">{renderSectionFields(id, custom)}</div> : null}
      </section>
    );
  }

  function renderSectionFields(id, custom) {
    const sections = draft.formData.sections;
    if (id === "summary") {
      return (
        <textarea value={sections.summary} onChange={(event) => updateSection("summary", event.target.value)} rows={5} />
      );
    }
    if (id === "skills") {
      return (
        <textarea value={sections.skills} onChange={(event) => updateSection("skills", event.target.value)} rows={5} />
      );
    }
    if (id === "education") {
      return (
        <>
          {sections.education.map((item, index) => (
            <div className="first-resume-repeat" key={index}>
              <div className="first-resume-grid">
                <label>Degree*<input value={item.degree} onChange={(event) => updateList("education", index, "degree", event.target.value)} /></label>
                <label>Institution*<input value={item.institution} onChange={(event) => updateList("education", index, "institution", event.target.value)} /></label>
                <label>Start Date<input value={item.start_date} onChange={(event) => updateList("education", index, "start_date", event.target.value)} /></label>
                <label>End Date<input value={item.end_date} onChange={(event) => updateList("education", index, "end_date", event.target.value)} /></label>
                <label>GPA<input value={item.gpa} onChange={(event) => updateList("education", index, "gpa", event.target.value)} /></label>
                <label>Coursework<input value={item.coursework} onChange={(event) => updateList("education", index, "coursework", event.target.value)} /></label>
              </div>
              {sections.education.length > 1 ? <button type="button" className="secondary-button compact-button" onClick={() => removeListItem("education", index)}>Remove</button> : null}
            </div>
          ))}
          <button type="button" className="secondary-button compact-button" onClick={() => addListItem("education")}>+ Add Education</button>
        </>
      );
    }
    if (id === "experience") {
      return (
        <>
          {sections.experience.map((item, index) => (
            <div className="first-resume-repeat" key={index}>
              <div className="first-resume-grid">
                <label>Title<input value={item.title} onChange={(event) => updateList("experience", index, "title", event.target.value)} /></label>
                <label>Company<input value={item.company} onChange={(event) => updateList("experience", index, "company", event.target.value)} /></label>
                <label>Start Date<input value={item.start_date} onChange={(event) => updateList("experience", index, "start_date", event.target.value)} /></label>
                <label>End Date<input disabled={item.current} value={item.end_date} onChange={(event) => updateList("experience", index, "end_date", event.target.value)} /></label>
              </div>
              <label className="checkbox-row"><input type="checkbox" checked={item.current} onChange={(event) => updateList("experience", index, "current", event.target.checked)} /> currently work here</label>
              <label>Bullet points one per line<textarea value={item.bullets} onChange={(event) => updateList("experience", index, "bullets", event.target.value)} rows={5} /></label>
              {sections.experience.length > 1 ? <button type="button" className="secondary-button compact-button" onClick={() => removeListItem("experience", index)}>Remove</button> : null}
            </div>
          ))}
          <button type="button" className="secondary-button compact-button" onClick={() => addListItem("experience")}>+ Add Experience</button>
        </>
      );
    }
    if (id === "projects") {
      return (
        <>
          {sections.projects.map((item, index) => (
            <div className="first-resume-repeat" key={index}>
              <div className="first-resume-grid">
                <label>Name<input value={item.name} onChange={(event) => updateList("projects", index, "name", event.target.value)} /></label>
                <label>Technologies<input value={item.technologies} onChange={(event) => updateList("projects", index, "technologies", event.target.value)} /></label>
                <label>Link<input value={item.link} onChange={(event) => updateList("projects", index, "link", event.target.value)} /></label>
              </div>
              <label>Description<textarea value={item.description} onChange={(event) => updateList("projects", index, "description", event.target.value)} rows={4} /></label>
              {sections.projects.length > 1 ? <button type="button" className="secondary-button compact-button" onClick={() => removeListItem("projects", index)}>Remove</button> : null}
            </div>
          ))}
          <button type="button" className="secondary-button compact-button" onClick={() => addListItem("projects")}>+ Add Project</button>
        </>
      );
    }
    return (
      <>
        {custom?.type === "Custom name" ? (
          <label>Section name<input value={custom.name} onChange={(event) => updateCustom(custom.id, "name", event.target.value)} /></label>
        ) : null}
        <textarea value={custom?.content || ""} onChange={(event) => updateCustom(custom.id, "content", event.target.value)} rows={5} />
        <button type="button" className="secondary-button compact-button" onClick={() => removeCustom(custom.id)}>Remove Section</button>
      </>
    );
  }

  return (
    <div className="first-resume-page stack page-enter">
      <div className="first-resume-header">
        <h2 className="page-title">Your First Resume</h2>
        <div className="first-resume-actions">
          <select value={draft.format} onChange={(event) => updateDraft((current) => ({ ...current, format: event.target.value }))}>
            {templateOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <label className="checkbox-row">
            <input type="checkbox" checked={draft.enhance} onChange={(event) => updateDraft((current) => ({ ...current, enhance: event.target.checked }))} />
            AI enhance
          </label>
        </div>
      </div>

      <div className="first-resume-workspace">
        <div className="first-resume-form">
          <section className="first-resume-pinned">
            <div className="first-resume-collapse-head"><strong>Personal Information</strong><span>Pinned</span></div>
            <div className="first-resume-grid">
              <label>Full Name*<input value={draft.formData.personal.name} onChange={(event) => updatePersonal("name", event.target.value)} /></label>
              <label>Email*<input value={draft.formData.personal.email} onChange={(event) => updatePersonal("email", event.target.value)} /></label>
              <label>Phone<input value={draft.formData.personal.phone} onChange={(event) => updatePersonal("phone", event.target.value)} /></label>
              <label>City/Country<input value={draft.formData.personal.location} onChange={(event) => updatePersonal("location", event.target.value)} /></label>
              <label>LinkedIn<input value={draft.formData.personal.linkedin} onChange={(event) => updatePersonal("linkedin", event.target.value)} /></label>
            </div>
          </section>

          <div className="first-resume-add-section">
            <select value={customChoice} onChange={(event) => setCustomChoice(event.target.value)}>
              <option value="">+ Add Section</option>
              {customOptions.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
            <button type="button" className="secondary-button compact-button" onClick={addCustomSection}>Add</button>
          </div>

          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext items={draft.sectionOrder} strategy={verticalListSortingStrategy}>
              {draft.sectionOrder.map((id) => {
                const title = baseSections.find((section) => section.id === id)?.title
                  || draft.formData.sections.custom_sections.find((section) => section.id === id)?.name
                  || "Custom Section";
                return <SortableSection key={id} id={id} title={title}>{renderSection(id)}</SortableSection>;
              })}
            </SortableContext>
          </DndContext>

          <div className="first-resume-bottom-bar">
            <button type="button" className="secondary-button" onClick={saveDraft}>Save Draft</button>
            <button type="button" className="secondary-button" onClick={clearAll}>Clear All</button>
            <button type="button" className="primary-button" onClick={generateResume}>Generate Resume</button>
          </div>
          {status ? <p className="muted-copy">{status}</p> : null}
          {error ? <p className="error-text">{error}</p> : null}
        </div>

        <div className="first-resume-preview">
          {generatedHtml ? (
            <div className="first-resume-preview-actions button-row">
              <strong>Live preview</strong>
              <div className="button-row" style={{ justifyContent: "flex-start" }}>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => exportResume("pdf")}
                  disabled={exporting === "pdf"}
                >
                  {exporting === "pdf" ? "Preparing PDF..." : "Export PDF"}
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => exportResume("docx")}
                  disabled={exporting === "docx" || !generatedCvData}
                >
                  {exporting === "docx" ? "Preparing DOCX..." : "Export DOCX"}
                </button>
              </div>
            </div>
          ) : null}
          <iframe title="First resume preview" srcDoc={previewHtml} />
        </div>
      </div>
    </div>
  );
}
