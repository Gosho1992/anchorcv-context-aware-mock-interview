import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import useAuthStore from "../store/useAuthStore";
import AIConcierge from "./AIConcierge";
import ThemeToggle from "./ThemeToggle";

// Canvas is the primary experience and the only prominent entry point. Everything
// the old tabs did is reachable via Canvas chips (job description, ATS check, live
// jobs, templates, build-from-scratch, discovery), and the full classic hub —
// Dashboard, Your First Resume, Templates and the other legacy pages — lives behind
// the unobtrusive "Advanced / Classic view" link (-> /dashboard-legacy) in the
// Canvas shell. This classic sidebar is trimmed to just account-level pages; every
// route still works by direct URL and via Canvas.
const navItems = [
  { to: "/files", label: "Files" },
  { to: "/account", label: "Account" },
];

export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, accessStatus, logout } = useAuthStore();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  const badgeType = accessStatus?.badge_type;
  const daysLeft = Number(accessStatus?.days_left || 0);
  const showUpgrade = Boolean(accessStatus?.show_upgrade);
  let accessBadgeLabel =
    badgeType === "trial"
      ? `🎁 Free trial · ${daysLeft} ${daysLeft === 1 ? "day" : "days"} left`
      : badgeType === "premium"
        ? `👑 Premium · ${daysLeft} ${daysLeft === 1 ? "day" : "days"} left`
        : badgeType === "expired"
          ? "Trial Ended"
          : "";
  if (badgeType === "premium" && daysLeft === 999) {
    accessBadgeLabel = "👑 Premium";
  }
  if (badgeType === "no_access") {
    accessBadgeLabel = "Upgrade Required";
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileMenuOpen ? "open" : ""}`}>
        <div className="sidebar-header">
          <div>
            <p
              className="eyebrow"
              style={{ display: "flex", alignItems: "center", gap: "6px" }}
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="5" r="3" />
                <line x1="12" y1="8" x2="12" y2="22" />
                <path d="M5 15l7 7 7-7" />
                <line x1="5" y1="11" x2="19" y2="11" />
              </svg>
              AnchorCV
            </p>
            <h1 className="brand-title">AnchorCV</h1>
            <p className="muted-copy">
              AI-powered CV builder for international students.
            </p>
          </div>

          <button
            type="button"
            className="secondary-button sidebar-toggle"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label={mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
            aria-expanded={mobileMenuOpen}
          >
            {mobileMenuOpen ? "✕" : "☰"}
          </button>
        </div>

        <nav className={`nav-list sidebar-body ${mobileMenuOpen ? "open" : ""}`}>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              className="nav-link"
              to={item.to}
              end={item.to === "/dashboard-legacy"}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className={`account-card sidebar-body ${mobileMenuOpen ? "open" : ""}`}>
          <p className="eyebrow">Signed in</p>
          <strong>
            {user?.first_name} {user?.last_name}
          </strong>
          <p className="muted-copy">{user?.email}</p>
          {accessBadgeLabel ? (
            <div className={`access-badge ${badgeType}`}>
              {accessBadgeLabel}
            </div>
          ) : null}
          {showUpgrade ? (
            <button
              type="button"
              className="primary-button compact-button"
              onClick={() => navigate("/payment")}
            >
              Upgrade to Premium
            </button>
          ) : null}
          <div style={{ marginTop: "var(--space-sm)" }}>
            <ThemeToggle />
          </div>
          <button className="secondary-button" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </aside>

      <main className="content">
        <Outlet />
      </main>

      <AIConcierge />
    </div>
  );
}
