import { useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import AIConcierge from "../AIConcierge";
import ThemeToggle from "../ThemeToggle";
import useAuthStore from "../../store/useAuthStore";
import useCanvasStore from "../../store/useCanvasStore";

function initialsFromUser(user) {
  const first = String(user?.first_name || "").trim();
  const last = String(user?.last_name || "").trim();
  const fallback = String(user?.email || "").trim();

  if (first || last) {
    return `${first[0] || ""}${last[0] || ""}`.toUpperCase() || "U";
  }
  if (fallback) {
    return fallback[0].toUpperCase();
  }
  return "U";
}

// Access badge derived from the same source the classic Dashboard uses:
// accessStatus.badge_type + days_left (from access_control.py via /auth/me).
function accessBadge(accessStatus) {
  const badgeType = accessStatus?.badge_type;
  const daysLeft = Number(accessStatus?.days_left || 0);
  const dayWord = daysLeft === 1 ? "day" : "days";
  if (badgeType === "premium") {
    return {
      label: daysLeft === 999 ? "👑 Premium" : `👑 Premium · ${daysLeft} ${dayWord} left`,
      color: "#22c55e",
    };
  }
  if (badgeType === "trial") {
    return { label: `🎁 Trial · ${daysLeft} ${dayWord} left`, color: "#f59e0b" };
  }
  if (badgeType === "expired") {
    return { label: "Trial ended", color: "#ef4444" };
  }
  if (badgeType === "no_access") {
    return { label: "Upgrade required", color: "#ef4444" };
  }
  return { label: "", color: "var(--text-secondary, #9ca3af)" };
}

export default function CanvasLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const navigate = useNavigate();
  const { user, logout, accessStatus } = useAuthStore();
  const cvText = useCanvasStore((state) => state.cvText);
  const cvFileName = useCanvasStore((state) => state.cvFileName);
  const openCvReplace = useCanvasStore((state) => state.openCvReplace);
  const hasCV = Boolean((cvText || "").trim());
  const access = accessBadge(accessStatus);

  function handleChangeCV() {
    openCvReplace();
    navigate("/canvas");
    setMobileMenuOpen(false);
  }

  async function handleLogout() {
    await logout();
    setMobileMenuOpen(false);
    navigate("/login");
  }

  const initials = initialsFromUser(user);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--bg-primary)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <header
        className="canvas-topbar"
        style={{
          minHeight: "60px",
          borderBottom: "1px solid var(--border)",
          background: "color-mix(in srgb, var(--bg-primary) 80%, transparent)",
          backdropFilter: "blur(12px)",
          position: "sticky",
          top: 0,
          zIndex: 50,
        }}
      >
        <div
          style={{
            maxWidth: "1200px",
            margin: "0 auto",
            height: "100%",
            padding: "0 clamp(0.85rem, 2vw, var(--space-xl))",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "var(--space-md)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.9rem", minWidth: 0 }}>
            <p className="eyebrow" style={{ margin: 0 }}>
              AnchorCV
            </p>
            {hasCV ? (
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.45rem",
                  fontSize: "0.8rem",
                  color: "var(--text-secondary, #9ca3af)",
                  border: "1px solid var(--border)",
                  borderRadius: "999px",
                  padding: "0.25rem 0.7rem",
                  minWidth: 0,
                }}
              >
                <span aria-hidden="true" style={{ color: "#22c55e" }}>✓</span>
                <span
                  style={{
                    maxWidth: "160px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={cvFileName || "extracted CV text"}
                >
                  CV: {cvFileName || "ready"}
                </span>
                <button
                  type="button"
                  onClick={handleChangeCV}
                  aria-label="Change current CV"
                  style={{
                    background: "none",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                    color: "var(--accent)",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                  }}
                >
                  Change
                </button>
              </span>
            ) : null}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", minWidth: 0 }}>
            <button
              type="button"
              className="secondary-button sidebar-toggle"
              onClick={() => setMobileMenuOpen((value) => !value)}
              aria-label={mobileMenuOpen ? "Close user menu" : "Open user menu"}
              aria-expanded={mobileMenuOpen}
            >
              {mobileMenuOpen ? "Close" : "Menu"}
            </button>
            <div
              className={`button-row sidebar-body ${mobileMenuOpen ? "open" : ""}`}
              style={{
                alignItems: "center",
                gap: "0.6rem",
                justifyContent: "flex-end",
              }}
            >
              {access.label ? (
                <span
                  aria-label="Access status"
                  title={access.label}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.35rem",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    border: "1px solid var(--border)",
                    borderRadius: "999px",
                    padding: "0.25rem 0.7rem",
                    whiteSpace: "nowrap",
                    color: access.color,
                  }}
                >
                  {access.label}
                </span>
              ) : null}
              <div
                title={`${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "User"}
                aria-label="User avatar"
                style={{
                  width: "34px",
                  height: "34px",
                  borderRadius: "50%",
                  border: "1px solid var(--border)",
                  background: "var(--bg-panel)",
                  display: "grid",
                  placeItems: "center",
                  color: "var(--text-primary)",
                  fontSize: "0.8rem",
                  fontWeight: 700,
                  flexShrink: 0,
                }}
              >
                {initials}
              </div>
              <ThemeToggle />
              <button
                type="button"
                className="secondary-button"
                onClick={handleLogout}
                style={{ padding: "0.55rem 1rem" }}
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="page-container canvas-content" style={{ maxWidth: "1200px", width: "100%", flex: 1 }}>
        <Outlet />
      </main>

      <AIConcierge />
    </div>
  );
}
