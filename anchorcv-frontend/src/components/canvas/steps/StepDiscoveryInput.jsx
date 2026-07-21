import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import DiscoveryInputControls from "../../DiscoveryInputControls";
import StepWrapper from "../StepWrapper";
import useCanvasStore from "../../../store/useCanvasStore";
import { postJson, postMultipart } from "../../../api/client";
import useAuthStore from "../../../store/useAuthStore";
import { trackCanvasEvent } from "../../../utils/canvasAnalytics";

export default function StepDiscoveryInput({ onComplete, onBack }) {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const accessStatus = useAuthStore((state) => state.accessStatus);
  const currentFlow = useCanvasStore((state) => state.currentFlow);
  const setDiscoveryData = useCanvasStore((state) => state.setDiscoveryData);

  const [query, setQuery] = useState("");
  const [intent, setIntent] = useState("job");
  const [region, setRegion] = useState("anywhere");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [resumeUploading, setResumeUploading] = useState(false);
  const [resumeFilename, setResumeFilename] = useState("");
  const [resumeText, setResumeText] = useState("");

  const fileInputRef = useRef(null);
  const isBlocked = accessStatus?.access === "blocked";
  const isPremium = accessStatus?.access === "premium";
  const quotaLabel = useMemo(() => (isPremium ? "Unlimited" : "Discovery mode"), [isPremium]);

  async function handleExplore() {
    if (isBlocked) {
      return;
    }
    const trimmed = (query || "").trim();
    if (!trimmed) {
      return;
    }

    setLoading(true);
    setError("");
    try {
      const data = await postJson("/discover/landscape", {
        query: `${trimmed} | region: ${region}`,
        intent,
        resume_text: resumeText || undefined,
      });
      setDiscoveryData(data);
      onComplete?.();
    } catch (err) {
      const message = err?.message || "Discovery search failed. Try editing your query and retry.";
      setError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: currentFlow || "discovery",
        step_name: "discoveryInput",
        error_type: "discovery_landscape_failed",
        message,
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleResumeFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    setResumeUploading(true);
    setError("");
    try {
      let extracted = "";
      if (file.name.toLowerCase().endsWith(".txt")) {
        extracted = await file.text();
      } else {
        const formData = new FormData();
        formData.append("file", file);
        const response = await postMultipart("/discover/extract-resume", formData);
        extracted = response?.resume_text || "";
      }
      setResumeFilename(file.name);
      setResumeText(extracted);
    } catch (err) {
      const message = err?.message || "Could not read resume file.";
      setError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: currentFlow || "discovery",
        step_name: "discoveryInput",
        error_type: "discovery_resume_extract_failed",
        message,
      });
    } finally {
      setResumeUploading(false);
    }
  }

  return (
    <StepWrapper
      title={`Discovery Input${user?.first_name ? ` - ${user.first_name}` : ""}`}
      description="Define intent and region, then generate your market landscape."
      onBack={onBack}
      maxWidth="100%"
    >
      <DiscoveryInputControls
        query={query}
        setQuery={setQuery}
        intent={intent}
        setIntent={setIntent}
        region={region}
        setRegion={setRegion}
        loading={loading}
        landscape={null}
        error={error}
        isBlocked={isBlocked}
        quotaLabel={quotaLabel}
        resumeUploading={resumeUploading}
        resumeFilename={resumeFilename}
        resumeText={resumeText}
        fileInputRef={fileInputRef}
        onExplore={handleExplore}
        onUpgrade={() => navigate("/payment")}
        onResumeFile={handleResumeFile}
        onClearResume={() => {
          setResumeFilename("");
          setResumeText("");
        }}
      />
    </StepWrapper>
  );
}
