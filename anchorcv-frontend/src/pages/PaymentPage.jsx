import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import useAuthStore from "../store/useAuthStore";
import { hasActivePremium } from "../utils/premium";

const CHECKOUT_STARTED_AT_KEY = "anchorcv_checkout_started_at";
const LEMON_CHECKOUT_URL =
  "https://anchorcv.lemonsqueezy.com/checkout/buy/e4843985-0685-4fc2-8aa7-2e2f03d28700";

export default function PaymentPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const autoStarted = useRef(false);
  const user = useAuthStore((state) => state.user);
  const [isRedirecting, setIsRedirecting] = useState(false);

  useEffect(() => {
    document.title = "Payment - AnchorCV";
  }, []);

  function redirectToCheckout() {
    setIsRedirecting(true);
    sessionStorage.setItem(CHECKOUT_STARTED_AT_KEY, new Date().toISOString());
    window.location.assign(LEMON_CHECKOUT_URL);
  }

  useEffect(() => {
    if (hasActivePremium(user)) {
      navigate("/", { replace: true });
    }
  }, [navigate, user]);

  useEffect(() => {
    if (location.state?.autoStartCheckout && !autoStarted.current) {
      autoStarted.current = true;
      redirectToCheckout();
    }
  }, [location.state?.autoStartCheckout]);

  return (
    <div className="screen-shell page-enter">
      <div className="auth-panel stack" style={{ width: "min(600px, 100%)" }}>
        <div className="stack tight">
          <p className="eyebrow">AnchorCV Premium</p>
          <h1 className="page-title" style={{ margin: 0 }}>
            Complete your setup.
          </h1>
          <p className="muted-copy" style={{ margin: 0 }}>
            90 days of full access. No auto-renewal. No subscription.
          </p>
        </div>

        <div className="analysis-meta-card stack" style={{ gap: "0.9rem" }}>
          <div className="payment-price">$29 — one-time payment</div>
          <p className="muted-copy" style={{ margin: 0 }}>
            {user?.email ? (
              <>
                You are checking out as <strong>{user.email}</strong>.
              </>
            ) : (
              "Your account is ready. Finish checkout to unlock the full toolkit."
            )}
          </p>
          <ul className="payment-feature-list" style={{ margin: 0 }}>
            <li>90 days of full access with no renewal trap</li>
            <li>Discovery landscapes for scholarships, jobs, and funding</li>
            <li>CV analysis, match scoring, and tailored application strategy</li>
            <li>CV exports plus cloud storage for generated files</li>
            <li>Chrome extension support for faster job capture</li>
          </ul>
        </div>

        <button
          className="primary-button"
          onClick={redirectToCheckout}
          disabled={isRedirecting}
        >
          {isRedirecting
            ? "Redirecting to secure checkout..."
            : "Continue to secure checkout"}
        </button>

        <p
          className="muted-copy"
          style={{ margin: 0, fontSize: "0.82rem", textAlign: "center" }}
        >
          Payments are handled by Lemon Squeezy.
        </p>

        <p
          className="muted-copy"
          style={{ margin: 0, fontSize: "0.85rem", textAlign: "center" }}
        >
          Already have an account?{" "}
          <Link
            to="/login"
            style={{ color: "var(--accent-soft)", fontWeight: 600 }}
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
