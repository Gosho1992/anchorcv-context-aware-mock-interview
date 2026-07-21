import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import useAuthStore from "../store/useAuthStore";
import { hasActivePremium } from "../utils/premium";

const PREMIUM_DURATION_DAYS = 90;
const EXTENSION_URL =
  "https://chromewebstore.google.com/detail/anchorcv/eooahhhcjoelmnfbfinhbnhhdggaogbe";

function buildPremiumSessionUser(user) {
  if (!user) {
    return user;
  }

  const expiresAt = new Date(
    Date.now() + PREMIUM_DURATION_DAYS * 24 * 60 * 60 * 1000
  ).toISOString();

  return {
    ...user,
    is_premium: true,
    is_paid: true,
    premium_expires_at: expiresAt,
  };
}

function buildPremiumAccessStatus(user) {
  const expiresAt = new Date(user?.premium_expires_at || 0).getTime();
  const daysLeft = Number.isFinite(expiresAt)
    ? Math.max(0, Math.ceil((expiresAt - Date.now()) / (1000 * 60 * 60 * 24)))
    : 90;

  return {
    access: "premium",
    days_left: daysLeft,
    badge_type: "premium",
    show_upgrade: false,
  };
}

export default function PaymentSuccessPage() {
  const navigate = useNavigate();
  const setUser = useAuthStore((state) => state.setUser);
  const user = useAuthStore((state) => state.user);
  const [countdown, setCountdown] = useState(10);
  const redirectTarget = user ? "/" : "/login";

  useEffect(() => {
    document.title = "Payment Success - AnchorCV";
  }, []);

  useEffect(() => {
    const currentUser = useAuthStore.getState().user;
    if (currentUser && !hasActivePremium(currentUser)) {
      const premiumUser = buildPremiumSessionUser(currentUser);
      setUser(premiumUser, buildPremiumAccessStatus(premiumUser));
    }

    sessionStorage.removeItem("anchorcv_checkout_started_at");

    const interval = window.setInterval(() => {
      setCountdown((current) => {
        if (current <= 1) {
          window.clearInterval(interval);
          navigate(redirectTarget, { replace: true });
          return 0;
        }
        return current - 1;
      });
    }, 1000);

    return () => window.clearInterval(interval);
  }, [navigate, redirectTarget, setUser]);

  return (
    <div className="screen-shell page-enter">
      <div className="auth-panel stack" style={{ maxWidth: "620px" }}>
        <div className="stack" style={{ textAlign: "center", alignItems: "center" }}>
          <div className="success-emoji">{"\u{1F389}"}</div>
          <p className="eyebrow">Payment Successful</p>
          <h1 className="page-title" style={{ margin: 0 }}>
            Premium activated.
          </h1>
          <p className="muted-copy" style={{ margin: 0, maxWidth: "34rem" }}>
            Your account now has full access to Discovery, Resume Intelligence,
            the CV Builder, and the Chrome extension workflow.
          </p>
          <p className="muted-copy" style={{ margin: 0 }}>
            Confirmation sent to <strong>{user?.email || "your email"}</strong>
          </p>
        </div>

        <div className="extension-card stack">
          <strong style={{ fontSize: "1rem" }}>Install the Chrome Extension</strong>
          <p className="muted-copy" style={{ margin: 0 }}>
            Generate tailored cover letters and professor emails directly from
            LinkedIn, Indeed, and JobsDB without copy-pasting.
          </p>
          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <a
              className="primary-button"
              href={EXTENSION_URL}
              target="_blank"
              rel="noreferrer"
            >
              Add to Chrome {"->"}
            </a>
            <button
              className="secondary-button"
              onClick={() => navigate("/", { replace: true })}
            >
              Go to your dashboard {"->"}
            </button>
          </div>
        </div>

        <p
          className="muted-copy"
          style={{ margin: 0, textAlign: "center", fontSize: "0.82rem" }}
        >
          Redirecting in {countdown}s...
        </p>
      </div>
    </div>
  );
}
