import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { getJson, postJson, postMultipart } from "../api/client";
import FileDropzone from "../components/FileDropzone";
import LoadingQuotes from "../components/LoadingQuotes";
import ModelSelect from "../components/ModelSelect";
import TemplateGallery, { TemplateDetail } from "../components/TemplateGallery";
import TemplateResultPanel from "../components/TemplateResultPanel";

const LOADING_QUOTES = [
  "Studying the target format's standards...",
  "Restructuring your experience to fit...",
  "The best CVs speak the reviewer's language...",
  "Checking section order and conventions...",
  "Almost there - polishing the structure...",
];

function buildExportDocument(templateName, html) {
  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>${templateName}</title>
    <style>
      body { font-family: Arial, sans-serif; max-width: 860px; margin: 0 auto; padding: 2rem; color: #1a1a1a; line-height: 1.5; }
      h1, h2, h3 { color: #1e3a5f; }
      h2 { border-bottom: 1px solid #d1d5db; padding-bottom: 4px; }
    </style>
  </head>
  <body>${html}</body>
</html>`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function TemplatesPage() {
  const [templates, setTemplates] = useState([]);
  const [loadError, setLoadError] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [file, setFile] = useState(null);
  const [targetRole, setTargetRole] = useState("");
  const [model, setModel] = useState("");
  const [action, setAction] = useState(""); // "convert" | "compare" | export types
  const [convertResult, setConvertResult] = useState(null);
  const [compareResult, setCompareResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    document.title = "CV Templates - AnchorCV";
    let isActive = true;

    getJson("/templates")
      .then((response) => {
        if (isActive && Array.isArray(response?.templates)) {
          setTemplates(response.templates);
        }
      })
      .catch(() => {
        if (isActive) {
          setLoadError("Could not load templates. Refresh to retry.");
        }
      });

    return () => {
      isActive = false;
    };
  }, []);

  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === selectedId) || null,
    [templates, selectedId]
  );

  function selectTemplate(id) {
    setSelectedId(id);
    setConvertResult(null);
    setCompareResult(null);
    setError("");
  }

  async function runAction(kind) {
    if (!file || !selectedTemplate) {
      return;
    }
    setAction(kind);
    setError("");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("template_id", selectedTemplate.id);
    if (model) {
      formData.append("model", model);
    }

    try {
      if (kind === "convert") {
        if (targetRole.trim()) {
          formData.append("target_role", targetRole.trim());
        }
        const result = await postMultipart("/templates/convert", formData);
        setConvertResult(result);
        setCompareResult(null);
      } else {
        const result = await postMultipart("/templates/compare", formData);
        setCompareResult(result);
        setConvertResult(null);
      }
    } catch (err) {
      setError(err?.message || "Something went wrong. Please try again.");
    } finally {
      setAction("");
    }
  }

  async function exportConverted(type) {
    if (!convertResult?.result_html) {
      return;
    }
    setAction(type);
    try {
      const html = buildExportDocument(convertResult.template_name, convertResult.result_html);
      const filename = `anchorcv-${convertResult.template_id}.${type}`;
      const blob = await postJson(`/export/${type}`, { html, filename });
      downloadBlob(blob, filename);
      toast.success(`${type.toUpperCase()} downloaded.`);
    } catch (err) {
      setError(err?.message || `${type.toUpperCase()} export failed.`);
    } finally {
      setAction("");
    }
  }

  const busy = action === "convert" || action === "compare";

  return (
    <section className="stack page-enter">
      <div className="stack tight">
        <p className="eyebrow">Templates</p>
        <h2 className="page-title">World-Class CV Templates</h2>
        <p className="muted-copy" style={{ margin: 0 }}>
          Convert your CV into the formats top institutions expect — or score it
          against their standards to see exactly what is missing.
        </p>
      </div>

      {loadError ? (
        <div className="analysis-meta-card warn">
          <p style={{ margin: 0 }}>{loadError}</p>
        </div>
      ) : null}

      <TemplateGallery templates={templates} selectedId={selectedId} onSelect={selectTemplate} />

      {selectedTemplate ? (
        <div className="panel stack">
          <TemplateDetail template={selectedTemplate} />

          <FileDropzone
            label="Upload your current CV"
            file={file}
            onChange={setFile}
            accept=".pdf,.docx,.txt"
          />

          <div className="button-row" style={{ justifyContent: "flex-start", alignItems: "flex-end", flexWrap: "wrap" }}>
            <label className="stack tight" style={{ flex: 1, minWidth: "220px" }}>
              <span className="eyebrow">Target role / position (optional)</span>
              <input
                className="input-modern"
                placeholder="e.g. Senior Public Sector Specialist"
                value={targetRole}
                onChange={(event) => setTargetRole(event.target.value)}
              />
            </label>
            <ModelSelect value={model} onChange={setModel} disabled={busy} compact />
          </div>

          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <button
              type="button"
              className="primary-button"
              onClick={() => runAction("convert")}
              disabled={!file || busy}
            >
              {action === "convert" ? "Converting..." : `Convert to ${selectedTemplate.name}`}
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => runAction("compare")}
              disabled={!file || busy}
            >
              {action === "compare" ? "Scoring..." : "Compare & Score My CV"}
            </button>
          </div>

          {busy ? (
            <LoadingQuotes
              quotes={LOADING_QUOTES}
              note="This usually takes 10-25 seconds."
            />
          ) : null}

          {error ? (
            <div className="analysis-meta-card warn">
              <p style={{ margin: 0 }}>{error}</p>
            </div>
          ) : null}

          <TemplateResultPanel
            compareResult={compareResult}
            convertResult={convertResult}
            onConvert={() => runAction("convert")}
            onExport={exportConverted}
            exporting={action}
            busy={busy}
          />
        </div>
      ) : templates.length > 0 ? (
        <div className="analysis-meta-card">
          <p style={{ margin: 0 }} className="muted-copy">
            Select a template above to see its structure, expectations, and to
            convert or score your CV.
          </p>
        </div>
      ) : null}
    </section>
  );
}
