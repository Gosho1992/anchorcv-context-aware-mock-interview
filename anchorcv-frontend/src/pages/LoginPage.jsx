import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import useAuthStore from "../store/useAuthStore";

const INITIAL_FORM = {
  first_name: "",
  last_name: "",
  email: "",
  country: "",
  password: "",
};

const POST_LOGIN_BLOCKED_TARGETS = new Set([
  "/login",
  "/payment",
  "/payment-success",
]);

function getReadableError(error) {
  if (!error) {
    return "";
  }

  if (typeof error === "string") {
    return error;
  }

  if (typeof error.detail === "string" && error.detail.trim()) {
    return error.detail;
  }

  if (Array.isArray(error.detail) && error.detail.length > 0) {
    return error.detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (typeof item?.msg === "string") {
          return item.msg;
        }
        return JSON.stringify(item);
      })
      .join(", ");
  }

  if (
    typeof error.message === "string" &&
    error.message.trim() &&
    error.message !== "[object Object]"
  ) {
    return error.message;
  }

  try {
    return JSON.stringify(error);
  } catch {
    return "Something went wrong.";
  }
}

function safePostLoginTarget(from) {
  if (!from || typeof from !== "string") {
    return "/";
  }

  if (POST_LOGIN_BLOCKED_TARGETS.has(from)) {
    return "/";
  }

  return from;
}

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, register, error, status } = useAuthStore();

  const [mode, setMode] = useState("login");
  const [form, setForm] = useState(INITIAL_FORM);
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const from = location.state?.from?.pathname || "/";
  const isLogin = mode === "login";

  useEffect(() => {
    document.title = "Login - AnchorCV";
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitError("");

    try {
      if (isLogin) {
        await login({ email: form.email, password });
        navigate(safePostLoginTarget(from), { replace: true });
        return;
      }

      await register({ ...form, password });
      navigate(safePostLoginTarget(from), { replace: true });
    } catch (submitFailure) {
      setSubmitError(getReadableError(submitFailure));
    }
  }

  return (
    <div className="auth-shell auth-shell-split login-layout">
      <aside className="auth-marketing auth-marketing-slab login-marketing">
        <div className="auth-wordmark">{"\u2693"} AnchorCV</div>

        <div className="stack tight">
          <p className="eyebrow">Your honest career partner</p>
          <h1
            className="auth-tagline"
            style={{ margin: 0, fontSize: "2.6rem", lineHeight: 1.08 }}
          >
            Your honest career partner for studying and working abroad.
          </h1>
          <p className="muted-copy" style={{ margin: 0, maxWidth: "38rem" }}>
            Discovery, CV analysis, tailored applications, and structured next
            steps for international students who need clarity, not fluff.
          </p>
        </div>

        <ul className="auth-benefits">
          <li>ATS-optimized CVs in 4 formats</li>
          <li>Cover letters that sound like you</li>
          <li>Emails professors actually read</li>
          <li>Discover scholarships worldwide</li>
          <li>90-day access, one-time payment</li>
        </ul>

        <div className="auth-proof-row">
          <div>
            <strong>Trusted by international students worldwide</strong>
            <p className="muted-copy" style={{ margin: "0.25rem 0 0" }}>
              Start with Discovery, then move straight into the documents that
              get you shortlisted.
            </p>
          </div>
          <div className="auth-price-tag">$19 for 90 days</div>
        </div>
      </aside>

      <div className="auth-panel auth-form-card stack login-form">
        <div className="stack tight">
          <p className="eyebrow">{isLogin ? "Welcome back" : "Create account"}</p>
          <h2 className="page-title" style={{ margin: 0 }}>
            {isLogin ? "Sign in to continue." : "Set up your AnchorCV access."}
          </h2>
          <p className="muted-copy" style={{ margin: 0 }}>
            {isLogin
              ? "Pick up where you left off across discovery, analysis, and CV building."
              : "One account, one payment, and 90 days of full access across the entire toolkit."}
          </p>
        </div>

        <div className="segmented-control">
          <button
            className={isLogin ? "active" : ""}
            onClick={() => setMode("login")}
          >
            Login
          </button>
          <button
            className={!isLogin ? "active" : ""}
            onClick={() => setMode("register")}
          >
            Register
          </button>
        </div>

        <form className="stack" onSubmit={handleSubmit}>
          {!isLogin ? (
            <>
              <input
                placeholder="First name"
                autoComplete="given-name"
                value={form.first_name}
                onChange={(event) =>
                  setForm({ ...form, first_name: event.target.value })
                }
              />
              <input
                placeholder="Last name"
                autoComplete="family-name"
                value={form.last_name}
                onChange={(event) =>
                  setForm({ ...form, last_name: event.target.value })
                }
              />
              <input
                placeholder="Country"
                autoComplete="country-name"
                value={form.country}
                onChange={(event) =>
                  setForm({ ...form, country: event.target.value })
                }
              />
            </>
          ) : null}

          <input
            type="email"
            placeholder="Email"
            autoComplete="email"
            value={form.email}
            onChange={(event) =>
              setForm({ ...form, email: event.target.value })
            }
          />

          <div className="auth-password-row">
            <input
              type={showPassword ? "text" : "password"}
              placeholder="Password"
              autoComplete={isLogin ? "current-password" : "new-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <button
              type="button"
              className="secondary-button"
              onClick={() => setShowPassword(!showPassword)}
              style={{ whiteSpace: "nowrap" }}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>

          {submitError || error ? (
            <p className="error-text" style={{ margin: 0 }}>
              {submitError || getReadableError(error)}
            </p>
          ) : null}

          <button
            type="submit"
            className="primary-button"
            disabled={status === "loading"}
          >
            {status === "loading"
              ? "Please wait..."
              : isLogin
                ? "Sign in"
                : "Create account"}
          </button>

          <button
            type="button"
            className="text-link-button"
            onClick={() => navigate("/forgot-password")}
          >
            Forgot password?
          </button>
        </form>
      </div>
    </div>
  );
}
