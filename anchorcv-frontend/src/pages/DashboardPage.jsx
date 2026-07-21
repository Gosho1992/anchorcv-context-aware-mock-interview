import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getJson } from "../api/client";
import useAuthStore from "../store/useAuthStore";
import useCanvasStore from "../store/useCanvasStore";
import useCvWorkspaceStore from "../store/useCvWorkspaceStore";

const EXTENSION_URL =
  "https://chromewebstore.google.com/detail/anchorcv/eooahhhcjoelmnfbfinhbnhhdggaogbe";

function daysUntil(isoDate) {
  if (!isoDate) return null;
  const expires = new Date(isoDate);
  if (Number.isNaN(expires.getTime())) return null;
  const diffMs = expires.getTime() - Date.now();
  return Math.max(0, Math.ceil(diffMs / (1000 * 60 * 60 * 24)));
}

function formatActivityDate(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleDateString();
  } catch {
    return value;
  }
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { user, accessStatus } = useAuthStore();
  const isPremium = accessStatus?.access === "premium";
  const isBlocked = accessStatus?.access === "blocked";
  const isFirstVisit = Boolean(user) && !user.onboarded_at;
  const days = accessStatus?.days_left ?? daysUntil(user?.premium_expires_at);
  const analysisResult = useCvWorkspaceStore((s) => s.analysisResult);
  const canvasCvText = useCanvasStore((s) => s.cvText);
  const canvasCvFileName = useCanvasStore((s) => s.cvFileName);
  const openCvReplace = useCanvasStore((s) => s.openCvReplace);

  const [stats, setStats] = useState({
    analyses: 0,
    cvs_built: 0,
    files: 0,
  });
  const [activity, setActivity] = useState([]);
  const [statsLoading, setStatsLoading] = useState(true);
  const [activityLoading, setActivityLoading] = useState(true);

  useEffect(() => {
    document.title = "Dashboard · AnchorCV";
  }, []);

  useEffect(() => {
    let active = true;

    async function loadStats() {
      setStatsLoading(true);
      try {
        const response = await getJson("/auth/me/stats");
        if (!active) return;
        setStats({
          analyses: Number(response?.analyses || 0),
          cvs_built: Number(response?.cvs_built || 0),
          files: Number(response?.files || 0),
        });
      } catch {
        if (!active) return;
        setStats({
          analyses: 0,
          cvs_built: 0,
          files: 0,
        });
      } finally {
        if (active) {
          setStatsLoading(false);
        }
      }
    }

    if (user) {
      loadStats();
    } else {
      setStatsLoading(false);
    }

    return () => {
      active = false;
    };
  }, [user]);

  useEffect(() => {
    let active = true;

    async function loadActivity() {
      setActivityLoading(true);
      try {
        const response = await getJson("/auth/me/activity");
        if (!active) return;
        setActivity(Array.isArray(response?.activity) ? response.activity : []);
      } catch {
        if (!active) return;
        setActivity([]);
      } finally {
        if (active) {
          setActivityLoading(false);
        }
      }
    }

    if (user) {
      loadActivity();
    } else {
      setActivityLoading(false);
    }

    return () => {
      active = false;
    };
  }, [user]);

  return (
    <section className="stack page-enter" style={{ gap: "1.5rem" }}>
      {/* Previous analysis banner */}
      {analysisResult && (
        <div className="analysis-banner">
          <div>
            <strong style={{ fontSize: "0.95rem" }}>📄 Previous analysis available</strong>
            <p className="muted-copy" style={{ margin: "0.25rem 0 0", fontSize: "0.85rem" }}>
              You have a saved analysis from your last session.
            </p>
          </div>
          <button
            className="primary-button"
            style={{ padding: "0.5rem 1.2rem", fontSize: "0.85rem" }}
            onClick={() => navigate("/analysis")}
          >
            Continue →
          </button>
        </div>
      )}

      <div
        className="hero-gradient"
        style={{ position: "relative", overflow: "hidden" }}
      >
        {/* Floating depth orbs */}
        <div style={{
          position: "absolute", top: "-60px", right: "-40px",
          width: "200px", height: "200px", borderRadius: "50%",
          background: "radial-gradient(circle, rgba(124,111,247,0.07) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />
        <div style={{
          position: "absolute", bottom: "-30px", left: "30%",
          width: "150px", height: "150px", borderRadius: "50%",
          background: "radial-gradient(circle, rgba(45,212,168,0.05) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: "1.5rem",
            flexWrap: "wrap",
            position: "relative",
          }}
        >
          <div style={{ flex: 1, minWidth: "280px" }}>
            <p className="eyebrow">
              {isFirstVisit ? "Welcome to AnchorCV" : "Welcome back"}
            </p>
            <h2
              className="hero-greeting"
              style={{ margin: "0.35rem 0 0.75rem", fontSize: "2rem", lineHeight: 1.15 }}
            >
              {isFirstVisit
                ? `Your next move starts here, ${user?.first_name || "there"}.`
                : `${user?.first_name || "Welcome back"} — let’s keep the momentum going.`}
            </h2>
            <p className="muted-copy" style={{ maxWidth: "640px", margin: 0, fontSize: "1rem" }}>
              {isFirstVisit
                ? "Use Discovery to map the fields, scholarships, and opportunities that match your background, then move straight into CV analysis and tailored documents."
                : "Jump back into discovery, sharpen your CV, or generate application materials without losing your progress."}
            </p>

            <div className="action-button-row dashboard-hero-actions">
              <button
                className="primary-button"
                onClick={() => (isBlocked ? navigate("/payment") : navigate("/discover"))}
              >
                {isBlocked ? "Upgrade to Premium" : "Discover"}
              </button>
              <button
                className="secondary-button"
                disabled={isBlocked}
                onClick={() => navigate("/analysis")}
                title={isBlocked ? "Upgrade required" : undefined}
              >
                Analyze CV
              </button>
              <button
                className="secondary-button"
                disabled={isBlocked}
                onClick={() => navigate("/builder")}
                title={isBlocked ? "Upgrade required" : undefined}
              >
                Build CV
              </button>
            </div>

            {(canvasCvText || "").trim() ? (
              <div
                style={{
                  marginTop: "1rem",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.55rem",
                  fontSize: "0.85rem",
                  color: "var(--text-secondary, #9ca3af)",
                  border: "1px solid var(--border)",
                  borderRadius: "999px",
                  padding: "0.35rem 0.85rem",
                }}
              >
                <span aria-hidden="true" style={{ color: "#22c55e" }}>✓</span>
                <span
                  style={{
                    maxWidth: "220px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={canvasCvFileName || "extracted CV text"}
                >
                  Current CV: <strong>{canvasCvFileName || "ready"}</strong>
                </span>
                <button
                  type="button"
                  aria-label="Change current CV"
                  onClick={() => {
                    openCvReplace();
                    navigate("/canvas");
                  }}
                  style={{
                    background: "none",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                    color: "var(--accent)",
                    fontSize: "0.85rem",
                    fontWeight: 600,
                  }}
                >
                  Change
                </button>
              </div>
            ) : null}
          </div>

          {isPremium && days !== null ? (
            <div className={`premium-chip ${days < 14 ? "warn" : ""}`}>
              <p className="eyebrow" style={{ margin: 0, color: "var(--text-secondary)" }}>
                Premium access
              </p>
              <p className="premium-chip-number">{days}</p>
              <p className="muted-copy" style={{ margin: 0, fontSize: "0.82rem" }}>
                {days === 1 ? "day remaining" : "days remaining"}
              </p>
            </div>
          ) : null}
        </div>
      </div>

      {isBlocked ? (
        <div className="access-block-card">
          <div>
            <h3>Your trial has ended. Upgrade to continue using AnchorCV.</h3>
            <p className="muted-copy" style={{ margin: "0.35rem 0 0" }}>
              Premium restores analysis, CV building, exports, matching, and discovery.
            </p>
          </div>
          <button className="primary-button" onClick={() => navigate("/payment")}>
            Upgrade to Premium
          </button>
        </div>
      ) : null}

      <div className="bento-grid">
        <div
          className={`bento-card dashboard-card panel-interactive accent-teal clickable card-enter-1 ${isBlocked ? "locked" : ""}`}
          onClick={() => (!isBlocked ? navigate("/discover") : null)}
          role="button"
          tabIndex={0}
          aria-disabled={isBlocked}
          onKeyDown={(event) => {
            if (!isBlocked && (event.key === "Enter" || event.key === " ")) {
              navigate("/discover");
            }
          }}
        >
          <div className="bento-card-head">
            <h3>{isBlocked ? "🔒 " : ""}Discovery</h3>
          </div>
          <p className="muted-copy" style={{ margin: 0, fontSize: "0.92rem" }}>
            Explore related fields, scholarships, and funding programs that fit
            your background.
          </p>
          {isFirstVisit ? (
            <span className="start-here-pill">Start here →</span>
          ) : (
            <span className="muted-copy" style={{ fontSize: "0.82rem" }}>
              Open Discovery →
            </span>
          )}
        </div>

        <div
          className="bento-card dashboard-card panel-interactive clickable card-enter-2"
          onClick={() => navigate("/first-resume")}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              navigate("/first-resume");
            }
          }}
        >
          <div className="bento-card-head">
            <h3>Your First Resume</h3>
          </div>
          <p className="muted-copy" style={{ margin: 0, fontSize: "0.92rem" }}>
            No CV yet? Build your first professional resume from scratch.
          </p>
          <span className="muted-copy" style={{ fontSize: "0.82rem" }}>
            Start from scratch →
          </span>
        </div>

        <div className="bento-card dashboard-card panel-interactive card-enter-2">
          <div className="bento-card-head">
            <h3>Recent activity</h3>
          </div>
          {activityLoading ? (
            <p className="muted-copy" style={{ margin: 0, fontSize: "0.9rem" }}>
              Loading activity…
            </p>
          ) : activity.length === 0 ? (
            <p className="muted-copy" style={{ margin: 0, fontSize: "0.9rem" }}>
              No recent activity yet. Your discoveries, analyses, and generated
              files will appear here.
            </p>
          ) : (
            <div className="stack tight">
              {activity.slice(0, 4).map((item, index) => (
                <div
                  key={`${item?.title || item?.type || "activity"}-${index}`}
                  style={{
                    paddingTop: "0.55rem",
                    borderTop: "1px solid var(--border)",
                  }}
                >
                  <strong style={{ display: "block", fontSize: "0.92rem" }}>
                    {item?.title || item?.label || item?.type || "Activity"}
                  </strong>
                  <p className="muted-copy" style={{ margin: "0.2rem 0 0", fontSize: "0.82rem" }}>
                    {item?.description || item?.summary || "Recent progress saved to your workspace."}
                  </p>
                  {(item?.created_at || item?.timestamp) ? (
                    <p className="subtle-copy" style={{ margin: "0.2rem 0 0", fontSize: "0.76rem" }}>
                      {formatActivityDate(item.created_at || item.timestamp)}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bento-card dashboard-card panel-interactive accent-amber card-enter-3">
          <div className="bento-card-head">
            <h3>Workspace stats</h3>
          </div>
          {statsLoading ? (
            <p className="muted-copy" style={{ margin: 0, fontSize: "0.9rem" }}>
              Loading stats…
            </p>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                gap: "0.75rem",
              }}
            >
              <div className="panel" style={{ padding: "1rem" }}>
                <strong style={{ display: "block", fontSize: "1.4rem" }}>
                  {stats.analyses}
                </strong>
                <span className="muted-copy" style={{ fontSize: "0.8rem" }}>
                  Analyses
                </span>
              </div>
              <div className="panel" style={{ padding: "1rem" }}>
                <strong style={{ display: "block", fontSize: "1.4rem" }}>
                  {stats.cvs_built}
                </strong>
                <span className="muted-copy" style={{ fontSize: "0.8rem" }}>
                  CVs built
                </span>
              </div>
              <div className="panel" style={{ padding: "1rem" }}>
                <strong style={{ display: "block", fontSize: "1.4rem" }}>
                  {stats.files}
                </strong>
                <span className="muted-copy" style={{ fontSize: "0.8rem" }}>
                  Files
                </span>
              </div>
            </div>
          )}
        </div>

        <div
          className={`bento-card dashboard-card panel-interactive accent-indigo clickable card-enter-4 ${isBlocked ? "locked" : ""}`}
          onClick={() => (!isBlocked ? window.open(EXTENSION_URL, "_blank", "noopener,noreferrer") : null)}
          role="button"
          tabIndex={0}
          aria-disabled={isBlocked}
          onKeyDown={(event) => {
            if (!isBlocked && (event.key === "Enter" || event.key === " ")) {
              window.open(EXTENSION_URL, "_blank", "noopener,noreferrer");
            }
          }}
        >
          <div className="bento-card-head">
            <h3>{isBlocked ? "🔒 " : ""}Chrome extension</h3>
          </div>
          <p className="muted-copy" style={{ margin: 0, fontSize: "0.92rem" }}>
            Generate cover letters and professor emails directly from LinkedIn,
            Indeed, and JobsDB in one click.
          </p>
          <span className="muted-copy" style={{ fontSize: "0.82rem" }}>
            Add to Chrome →
          </span>
        </div>
      </div>

      {isFirstVisit ? (
        <div className="onboarding-checklist">
          <h3 style={{ margin: "0 0 1rem", fontSize: "1.05rem" }}>
            Start in 3 steps
          </h3>
          <div>
            {[
              {
                step: 1,
                text: "Describe what you want and generate your first discovery landscape.",
                link: "/discover",
                cta: "Discover",
              },
              {
                step: 2,
                text: "Upload your CV and compare it against a job or scholarship target.",
                link: "/analysis",
                cta: "Analyze",
              },
              {
                step: 3,
                text: "Turn that guidance into a polished, tailored CV you can export.",
                link: "/builder",
                cta: "Build",
              },
            ].map((item) => (
              <div key={item.step} className="onboarding-step">
                <span className="onboarding-step-num">{item.step}</span>
                <span className="onboarding-step-text">{item.text}</span>
                <button
                  className="secondary-button compact-button"
                  onClick={() => navigate(item.link)}
                >
                  {item.cta} →
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
