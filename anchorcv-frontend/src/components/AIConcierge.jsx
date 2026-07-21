import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { postJson } from "../api/client";
import useAuthStore from "../store/useAuthStore";
import useCanvasStore from "../store/useCanvasStore";
import useCvWorkspaceStore from "../store/useCvWorkspaceStore";
import { hasActivePremium } from "../utils/premium";

const INACTIVITY_MS = 2 * 60 * 1000; // 2 minutes
const CACHE_TTL_MS = 5 * 60 * 1000;  // 5 minutes

function pageName(pathname) {
  if (pathname === "/" || pathname === "") return "dashboard";
  const seg = pathname.replace(/^\//, "").split("/")[0];
  const map = {
    canvas: "canvas",
    discover: "discover",
    "first-resume": "first-resume",
    analysis: "analysis",
    builder: "builder",
    files: "files",
    account: "account",
  };
  return map[seg] || "dashboard";
}

export default function AIConcierge() {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  const analysisResult = useCvWorkspaceStore((s) => s.analysisResult);
  const builderResult = useCvWorkspaceStore((s) => s.builderResult);
  const analysisOutputType = useCvWorkspaceStore((s) => s.analysisOutputType);
  const builderTarget = useCvWorkspaceStore((s) => s.builderTarget);
  const uploadedResumeFile = useCvWorkspaceStore((s) => s.uploadedResumeFile);
  const setAnalysisOutputType = useCvWorkspaceStore((s) => s.setAnalysisOutputType);
  const canvasFlow = useCanvasStore((s) => s.currentFlow);
  const canvasStep = useCanvasStore((s) => s.currentStep);
  const canvasCvText = useCanvasStore((s) => s.cvText);
  const canvasResults = useCanvasStore((s) => s.generatedResults);

  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const cache = useRef({});
  const inactivityTimer = useRef(null);
  const hasAutoOpened = useRef(false);
  const panelRef = useRef(null);

  const currentPage = pageName(location.pathname);

  const buildContext = useCallback(() => {
    const scoreFromResult = () => {
      if (!analysisResult) return null;
      const scores = [
        analysisResult.skill_match_score,
        analysisResult.experience_match_score,
        analysisResult.keyword_match_score,
      ].filter((s) => typeof s === "number");
      if (!scores.length) return null;
      return Math.round(scores.reduce((a, b) => a + b, 0) / scores.length);
    };

    const isNew =
      !user?.created_at ||
      Date.now() - new Date(user.created_at).getTime() < 3 * 24 * 60 * 60 * 1000;
    const hasCanvasResults =
      canvasResults && typeof canvasResults === "object"
        ? Object.keys(canvasResults).length > 0
        : false;
    const hasCv = uploadedResumeFile !== null || Boolean(canvasCvText);

    return {
      page: currentPage,
      flow: currentPage === "canvas" ? canvasFlow : null,
      step: currentPage === "canvas" ? canvasStep : null,
      hasCV: hasCv,
      hasResults: currentPage === "canvas" ? hasCanvasResults : false,
      has_cv_uploaded: hasCv,
      has_analysis_result: analysisResult !== null || hasCanvasResults,
      has_builder_result: builderResult !== null,
      last_analysis_score: scoreFromResult(),
      analysis_output_type: analysisOutputType || "",
      builder_target: builderTarget || "",
      is_new_user: isNew,
      is_premium: hasActivePremium(user),
    };
  }, [
    currentPage,
    uploadedResumeFile,
    canvasCvText,
    canvasFlow,
    canvasStep,
    canvasResults,
    analysisResult,
    builderResult,
    analysisOutputType,
    builderTarget,
    user,
  ]);

  const fetchSuggestions = useCallback(async () => {
    const cached = cache.current[currentPage];
    if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
      setData(cached.data);
      return;
    }
    setLoading(true);
    try {
      const result = await postJson("/navigate/", buildContext());
      cache.current[currentPage] = { data: result, fetchedAt: Date.now() };
      setData(result);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [currentPage, buildContext]);

  // Reset auto-open flag on page change
  useEffect(() => {
    hasAutoOpened.current = false;
    // Invalidate cache for the new page so fresh suggestions load
    delete cache.current[currentPage];
  }, [location.pathname]);

  // Inactivity timer -> auto-open once per page visit
  useEffect(() => {
    const inactivityMs =
      currentPage === "canvas" && (canvasStep === 0 || !canvasFlow)
        ? 30 * 1000
        : INACTIVITY_MS;

    const resetTimer = () => {
      clearTimeout(inactivityTimer.current);
      if (!open) {
        inactivityTimer.current = setTimeout(() => {
          if (!hasAutoOpened.current) {
            hasAutoOpened.current = true;
            setOpen(true);
          }
        }, inactivityMs);
      }
    };

    const events = ["mousemove", "keydown", "scroll", "click", "touchstart"];
    events.forEach((e) =>
      window.addEventListener(e, resetTimer, { passive: true })
    );
    resetTimer();

    return () => {
      clearTimeout(inactivityTimer.current);
      events.forEach((e) => window.removeEventListener(e, resetTimer));
    };
  }, [open, currentPage, canvasStep, canvasFlow]);

  // Fetch when panel opens
  useEffect(() => {
    if (open) fetchSuggestions();
  }, [open, fetchSuggestions]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function onOutside(e) {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        const fab = document.querySelector(".ai-concierge-fab");
        if (fab && fab.contains(e.target)) return;
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, [open]);

  function handleSuggestion(suggestion) {
    const actionType = suggestion.action_type;

    if (actionType === "navigate" && suggestion.payload?.path) {
      navigate(suggestion.payload.path);
    } else if (actionType === "open_builder") {
      navigate("/builder");
    } else if (actionType === "open_discover") {
      navigate("/discover");
    } else if (actionType === "set_output_type") {
      if (suggestion.payload?.output_type) {
        setAnalysisOutputType(suggestion.payload.output_type);
      }
      navigate("/analysis");
    }
    setOpen(false);
  }

  const fallback = {
    message: "How can I help you today?",
    suggestions: [],
  };

  const displayData = loading ? null : (data ?? fallback);

  return (
    <>
      <button
        className={`ai-concierge-fab${open ? " active" : ""}`}
        aria-label="AI Career Assistant"
        onClick={() => setOpen((prev) => !prev)}
      >
        {open ? (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        ) : (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        )}
      </button>

      <div className={`ai-concierge-panel${open ? " visible" : ""}`} ref={panelRef} aria-hidden={!open}>
        <div className="ai-concierge-header">
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span className="ai-concierge-dot" />
            <span className="eyebrow" style={{ margin: 0 }}>Career Assistant</span>
          </div>
          <button
            className="ai-concierge-close"
            onClick={() => setOpen(false)}
            aria-label="Close assistant"
          >
            X
          </button>
        </div>

        <div className="ai-concierge-body">
          {loading ? (
            <div className="ai-concierge-loading">
              <span className="ai-concierge-spinner" />
              <span className="muted-copy">Finding suggestions...</span>
            </div>
          ) : displayData ? (
            <>
              <p className="ai-concierge-message">{displayData.message}</p>
              {displayData.suggestions?.length > 0 && (
                <div className="ai-concierge-suggestions">
                  <button
                    className="ai-concierge-chip"
                    onClick={() =>
                      handleSuggestion({
                        action_type: "navigate",
                        payload: { path: "/first-resume" },
                      })
                    }
                  >
                    Your First Resume
                  </button>
                  {displayData.suggestions.map((s, i) => (
                    <button
                      key={i}
                      className="ai-concierge-chip"
                      onClick={() => handleSuggestion(s)}
                    >
                      {s.text}
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="muted-copy" style={{ textAlign: "center", margin: 0 }}>
              Something went wrong. Try again.
            </p>
          )}
        </div>
      </div>
    </>
  );
}

