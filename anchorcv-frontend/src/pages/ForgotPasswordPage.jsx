import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { postJson } from "../api/client";

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle"); // idle | loading | sent | error
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    document.title = "Forgot Password · AnchorCV";
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!email.trim()) return;
    setStatus("loading");
    setErrorMsg("");

    try {
      await postJson("/auth/forgot-password", { email: email.trim().toLowerCase() });
      setStatus("sent");
    } catch (err) {
      setErrorMsg(err?.message || "Something went wrong. Please try again.");
      setStatus("error");
    }
  }

  return (
    <div className="auth-shell auth-shell-split login-layout">
      <aside className="auth-marketing auth-marketing-slab login-marketing">
        <div className="auth-wordmark">⚓ AnchorCV</div>
        <div className="stack tight">
          <p className="eyebrow">Account recovery</p>
          <h1
            className="auth-tagline"
            style={{ margin: 0, fontSize: "2.2rem", lineHeight: 1.1 }}
          >
            Reset your password in seconds.
          </h1>
          <p className="muted-copy" style={{ margin: 0, maxWidth: "36rem" }}>
            Enter the email address you registered with and we'll send you a
            secure reset link — valid for one hour.
          </p>
        </div>
      </aside>

      <div className="auth-panel auth-form-card stack login-form">
        {status === "sent" ? (
          <div className="stack tight" style={{ textAlign: "center", paddingTop: "1rem" }}>
            <div style={{ fontSize: "2.8rem" }}>📬</div>
            <h2 className="page-title" style={{ margin: "0.5rem 0 0" }}>
              Check your inbox
            </h2>
            <p className="muted-copy" style={{ margin: "0.5rem 0 0" }}>
              If <strong>{email}</strong> is registered, you'll receive a reset
              link within a minute. Check your spam folder if you don't see it.
            </p>
            <button
              type="button"
              className="primary-button"
              style={{ marginTop: "1.25rem" }}
              onClick={() => navigate("/login")}
            >
              Back to sign in
            </button>
          </div>
        ) : (
          <>
            <div className="stack tight">
              <p className="eyebrow">Forgot your password?</p>
              <h2 className="page-title" style={{ margin: 0 }}>
                Send a reset link.
              </h2>
              <p className="muted-copy" style={{ margin: 0 }}>
                We'll email you a link to set a new password. No security
                questions, no hassle.
              </p>
            </div>

            <form className="stack" onSubmit={handleSubmit}>
              <input
                type="email"
                placeholder="Your email address"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />

              {errorMsg ? (
                <p className="error-text" style={{ margin: 0 }}>
                  {errorMsg}
                </p>
              ) : null}

              <button
                type="submit"
                className="primary-button"
                disabled={status === "loading"}
              >
                {status === "loading" ? "Sending…" : "Send reset link"}
              </button>

              <button
                type="button"
                className="text-link-button"
                onClick={() => navigate("/login")}
              >
                ← Back to sign in
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
