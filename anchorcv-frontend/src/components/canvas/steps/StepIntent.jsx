import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { postJson } from "../../../api/client";
import useAuthStore from "../../../store/useAuthStore";
import useCanvasStore from "../../../store/useCanvasStore";

function inferFlowFromDiscovery(discoveryData) {
  const blob = JSON.stringify(discoveryData || {}).toLowerCase();
  if (blob.includes("scholarship") || blob.includes("fellowship")) {
    return "scholarship";
  }
  return "job";
}

function extractDiscoveryPrefill(discoveryData) {
  if (!discoveryData) {
    return "";
  }

  if (typeof discoveryData === "string") {
    return discoveryData.trim();
  }

  const keyCandidates = [
    "jdText",
    "job_description",
    "scholarship_details",
    "requirements",
    "description",
    "details",
    "summary",
    "text",
    "content",
    "opportunity",
    "selectedOpportunity",
  ];

  for (const key of keyCandidates) {
    const value = discoveryData[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }

    if (value && typeof value === "object") {
      const nested =
        value.requirements ||
        value.description ||
        value.details ||
        value.summary ||
        value.text ||
        value.content;
      if (typeof nested === "string" && nested.trim()) {
        return nested.trim();
      }
    }
  }

  if (Array.isArray(discoveryData.opportunities) && discoveryData.opportunities.length) {
    const first = discoveryData.opportunities[0];
    if (typeof first === "string" && first.trim()) {
      return first.trim();
    }
    if (first && typeof first === "object") {
      const nested =
        first.requirements ||
        first.description ||
        first.details ||
        first.summary ||
        first.text ||
        first.content;
      if (typeof nested === "string" && nested.trim()) {
        return nested.trim();
      }
    }
  }

  return "";
}

export default function StepIntent() {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const uploadedCV = useCanvasStore((state) => state.uploadedCV);
  const cvText = useCanvasStore((state) => state.cvText);
  const currentFlow = useCanvasStore((state) => state.currentFlow);
  const currentStep = useCanvasStore((state) => state.currentStep);
  const discoveryData = useCanvasStore((state) => state.discoveryData);
  const generatedResults = useCanvasStore((state) => state.generatedResults);
  const setFlow = useCanvasStore((state) => state.setFlow);
  const nextStep = useCanvasStore((state) => state.nextStep);
  const setJD = useCanvasStore((state) => state.setJD);
  const setSelectedOutputs = useCanvasStore((state) => state.setSelectedOutputs);

  const [personalizedHint, setPersonalizedHint] = useState("");
  const [conciergeSuggestions, setConciergeSuggestions] = useState([]);

  const firstName = user?.first_name?.trim() || "there";
  const isFirstVisit = !user?.onboarded_at;
  const heading = isFirstVisit
    ? `Welcome to AnchorCV, ${firstName}`
    : `Welcome back, ${firstName}`;

  useEffect(() => {
    let isActive = true;

    async function fetchPersonalizedHint() {
      try {
        const response = await postJson("/navigate/", {
          page: "canvas",
          flow: currentFlow || null,
          step: currentStep,
          hasCV: Boolean(uploadedCV || cvText),
          hasResults: Object.keys(generatedResults || {}).length > 0,
          has_cv_uploaded: Boolean(uploadedCV || cvText),
          has_analysis_result: false,
          has_builder_result: false,
          last_analysis_score: null,
          analysis_output_type: "",
          builder_target: "",
          is_new_user: isFirstVisit,
          is_premium: false,
        });

        if (isActive && typeof response?.message === "string" && response.message.trim()) {
          setPersonalizedHint(response.message.trim());
        }
        if (isActive && Array.isArray(response?.suggestions)) {
          setConciergeSuggestions(response.suggestions.slice(0, 3));
        }
      } catch {
        setPersonalizedHint("");
        setConciergeSuggestions([]);
      }
    }

    fetchPersonalizedHint();
    return () => {
      isActive = false;
    };
  }, [uploadedCV, cvText, isFirstVisit, currentFlow, currentStep, generatedResults]);

  const chips = useMemo(() => {
    const entries = [];
    const hasUploadedCV = Boolean(uploadedCV || cvText);
    const hasDiscoveryData = Boolean(discoveryData);

    if (hasUploadedCV) {
      entries.push({
        id: "continue_cv",
        title: "Continue with my last CV",
        description: "Resume with your existing CV context.",
        prominent: true,
        onClick: () => {
          setFlow(currentFlow || "job");
          nextStep();
        },
      });
    }

    if (hasDiscoveryData) {
      entries.push({
        id: "apply_from_discovery",
        title: "I found an opportunity - apply now",
        description: "Pre-fill requirements from your discovery results.",
        prominent: true,
        onClick: () => {
          const prefill = extractDiscoveryPrefill(discoveryData);
          if (prefill) {
            setJD(prefill);
          }
          setFlow(inferFlowFromDiscovery(discoveryData));
          nextStep();
        },
      });
    }

    entries.push(
      {
        id: "job",
        title: "I have a job description",
        description: "Tailor CV outputs for a specific role.",
        onClick: () => {
          setFlow("job");
          nextStep();
        },
      },
      {
        id: "atsCheck",
        title: "Check my CV against ATS",
        description: "Score your CV against a role's applicant tracking system.",
        onClick: () => {
          setFlow("atsCheck");
          nextStep();
        },
      },
      {
        id: "jobSearch",
        title: "Search live jobs",
        description: "Find live roles and tailor an application to any of them.",
        onClick: () => {
          setFlow("jobSearch");
          nextStep();
        },
      },
      {
        id: "scholarship",
        title: "I want to apply for a scholarship",
        description: "Align your application for funding opportunities.",
        onClick: () => {
          setFlow("scholarship");
          nextStep();
        },
      },
      {
        id: "interview",
        title: "Context-Aware Mock Interview",
        description: "A personalized interview generated from your resume and target job description.",
        onClick: () => {
          setFlow("interview");
          nextStep();
        },
      },

      {
        id: "improveResume",
        title: "Improve my existing resume",
        description: "Get rewrites, scores, and fixes for your current CV.",
        onClick: () => {
          setFlow("improveResume");
          nextStep();
        },
      },
      {
        id: "templates",
        title: "Use a world-class CV template",
        description: "World Bank, ADB, immigration, legal, and executive formats.",
        onClick: () => {
          setFlow("templates");
          nextStep();
        },
      },
      {
        id: "discovery",
        title: "Discover opportunities",
        description: "Map jobs, scholarships, and pathways by intent.",
        onClick: () => {
          setFlow("discovery");
          nextStep();
        },
      },
      {
        id: "buildCV",
        title: "Build a CV from scratch",
        description: "Start a fresh CV using AnchorCV guidance.",
        onClick: () => {
          setFlow("buildCV");
          nextStep();
        },
      }
    );

    return entries;
  }, [uploadedCV, cvText, discoveryData, currentFlow, setFlow, nextStep, setJD, navigate]);

  function handleConciergeSuggestion(suggestion) {
    const actionType = suggestion?.action_type;
    const path = suggestion?.payload?.path || "";

    if (actionType === "navigate") {
      if (path.includes("/discover")) {
        setFlow("discovery");
        nextStep();
        return;
      }
      if (path.includes("/analysis")) {
        setFlow("job");
        nextStep();
        return;
      }
      if (path.includes("/builder") || path.includes("/first-resume")) {
        setFlow("buildCV");
        nextStep();
        return;
      }
      if (path) {
        navigate(path);
      }
      return;
    }

    if (actionType === "set_output_type") {
      const outputType = suggestion?.payload?.output_type;
      setFlow("job");
      if (outputType) {
        setSelectedOutputs([outputType]);
      }
      nextStep();
      return;
    }

    if (actionType === "open_builder") {
      setFlow("buildCV");
      nextStep();
      return;
    }

    if (actionType === "open_discover") {
      setFlow("discovery");
      nextStep();
    }
  }

  return (
    <section className="stack page-enter">
      <div className="panel stack">
        <div className="stack tight">
          <p className="eyebrow">Canvas</p>
          <h2 className="page-title">{heading}</h2>
          <p className="muted-copy" style={{ margin: 0 }}>
            What are you working on today?
          </p>
          {personalizedHint ? (
            <p className="subtle-copy" style={{ margin: 0 }}>
              {personalizedHint}
            </p>
          ) : null}
        </div>

        <div
          className="card-grid"
          style={{
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          }}
        >
          {chips.map((chip, index) => {
            const enterClass = `card-enter-${Math.min(index + 1, 6)}`;
            return (
              <button
                key={chip.id}
                type="button"
                className={`panel-interactive stack tight ${enterClass}`}
                onClick={chip.onClick}
                style={{
                  alignItems: "flex-start",
                  textAlign: "left",
                  borderColor: chip.prominent
                    ? "color-mix(in srgb, var(--accent) 55%, var(--border))"
                    : undefined,
                  boxShadow: chip.prominent ? "var(--shadow-glow-accent)" : undefined,
                }}
              >
                <p className="eyebrow" style={{ margin: 0 }}>
                  {chip.prominent ? "Suggested" : "Start Here"}
                </p>
                <strong>{chip.title}</strong>
                <span className="muted-copy">{chip.description}</span>
              </button>
            );
          })}
        </div>

        {conciergeSuggestions.length > 0 ? (
          <div className="stack tight">
            <p className="eyebrow" style={{ margin: 0 }}>AI Suggestions</p>
            <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
              {conciergeSuggestions.map((suggestion, index) => (
                <button
                  key={`${suggestion?.text || "suggestion"}-${index}`}
                  type="button"
                  className={`panel-interactive stack tight card-enter-${Math.min(index + 1, 6)}`}
                  onClick={() => handleConciergeSuggestion(suggestion)}
                  style={{ textAlign: "left", alignItems: "flex-start" }}
                >
                  <p className="eyebrow" style={{ margin: 0 }}>Suggested</p>
                  <strong>{suggestion?.text || "Continue"}</strong>
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}


