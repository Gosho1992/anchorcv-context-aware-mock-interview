import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { listFiles } from "../api/client";
import useAuthStore from "../store/useAuthStore";
import { hasActivePremium } from "../utils/premium";

function daysUntil(isoDate) {
  if (!isoDate) {
    return null;
  }

  const expires = new Date(isoDate);
  if (Number.isNaN(expires.getTime())) {
    return null;
  }

  return Math.ceil((expires.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
}

export default function AccountPage() {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const filesQuery = useQuery({ queryKey: ["files"], queryFn: listFiles });

  const usedFromFiles = (filesQuery.data?.files || []).reduce(
    (sum, file) => sum + Number(file.size_bytes || 0),
    0
  );
  const usedFromUser = Number(user?.storage_used_bytes || 0);
  const used = Math.max(usedFromFiles, usedFromUser);
  const quota = Number(user?.storage_quota_bytes || 52428800);
  const percent = quota > 0 ? Math.min(100, Math.round((used / quota) * 100)) : 0;
  const isPremium = hasActivePremium(user);
  const remainingDays = daysUntil(user?.premium_expires_at);
  const premiumLabel =
    isPremium && remainingDays !== null
      ? `${remainingDays} ${remainingDays === 1 ? "day" : "days"} remaining`
      : "Expired - Renew now";

  useEffect(() => {
    document.title = "Account - AnchorCV";
  }, []);

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <section className="stack page-enter">
      <div className="panel stack">
        <div>
          <p className="eyebrow">Account</p>
          <h2 className="page-title">Profile and access</h2>
        </div>
      </div>

      <div className="panel stack">
        <div className="account-detail-row">
          <div>
            <strong style={{ fontSize: "1.05rem" }}>
              {user?.first_name} {user?.last_name}
            </strong>
            <p className="muted-copy" style={{ margin: "0.25rem 0 0" }}>
              {user?.email}
            </p>
          </div>
          <span className={`account-pill ${isPremium ? "" : "warn"}`}>
            {premiumLabel}
          </span>
        </div>

        <div className="stack tight">
          <div className="account-detail-row">
            <strong>Storage used</strong>
            <span className="muted-copy">{percent}%</span>
          </div>
          <div className={`meter ${percent > 80 ? "pulse-glow" : ""}`}>
            <div className="meter-fill" style={{ width: `${percent}%` }} />
          </div>
          <p className="muted-copy" style={{ margin: 0 }}>
            {Math.round(used / 1024 / 1024)} MB used out of{" "}
            {Math.round(quota / 1024 / 1024)} MB
          </p>
        </div>

        <div className="stack tight">
          <div className="placeholder-card">
            <div>
              <strong>Change Password</strong>
              <p className="muted-copy" style={{ margin: "0.25rem 0 0" }}>
                Coming soon
              </p>
            </div>
            <span className="muted-copy">Coming soon</span>
          </div>
          <div className="placeholder-card">
            <div>
              <strong>Billing History</strong>
              <p className="muted-copy" style={{ margin: "0.25rem 0 0" }}>
                Coming soon
              </p>
            </div>
            <span className="muted-copy">Coming soon</span>
          </div>
          <div className="placeholder-card">
            <div>
              <strong>Notification Preferences</strong>
              <p className="muted-copy" style={{ margin: "0.25rem 0 0" }}>
                Coming soon
              </p>
            </div>
            <span className="muted-copy">Coming soon</span>
          </div>
        </div>

        <div className="placeholder-card">
          <div>
            <strong>Classic view</strong>
            <p className="muted-copy" style={{ margin: "0.25rem 0 0" }}>
              The old tab-based dashboard, kept as a fallback.
            </p>
          </div>
          <button
            type="button"
            className="secondary-button compact-button"
            onClick={() => navigate("/dashboard-legacy")}
          >
            Open
          </button>
        </div>

        {!isPremium ? (
          <button
            className="secondary-button"
            onClick={() => navigate("/payment")}
          >
            Renew now
          </button>
        ) : null}

        <button className="primary-button" onClick={handleLogout}>
          Sign out
        </button>
      </div>
    </section>
  );
}
