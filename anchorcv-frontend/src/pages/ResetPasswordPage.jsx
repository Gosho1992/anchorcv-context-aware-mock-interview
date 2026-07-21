import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { postJson } from "../api/client";

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";

  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [status, setStatus] = useState("idle"); // idle | loading | success | error
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    document.title = "Reset Password · AnchorCV";
  }, []);

  // No token in URL — show an informative error immediately
  if (!token) {
    return (
      <div className="auth-shell auth-shell-split login-layout">
        <aside className="auth-marketing auth-marketing-slab login-marketing">
          <div className="auth-wordmark">⚓ AnchorCV</div>
        </aside>
        <div className="auth-panel auth-form-card stack login-form">
          <div className="stack tight" style={{ textAlign: "center", paddingTop: "1rem" }}>
            <div style={{ fontSize: "2.8rem" }}>⚠️</div>
            <h2 className="page-title" style={{ margin: "0.5rem 0 0" }}>
              Invalid reset link
            </h2>
            <p className="muted-copy" style={{ margin: "0.5rem 0 0" }}>
              This link is missing a reset token. Please request a new one.
            </p>
            <button
              type="button"
              className="primary-button"
              style={{ marginTop: "1.25rem" }}
              onClick={() => navigate("/forgot-password")}
            >
              Request new link
            </button>
          </div>
        </div>
      </div>
    );
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setErrorMsg("");

    if (newPassword.length < 8) {
      setErrorMsg("Password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirm) {
      setErrorMsg("Passwords don't match.");
      return;
    }

    setStatus("loading");
    try {
      await postJson("/auth/reset-password", { token, new_password: newPassword });
      setStatus("success");
    } catch (err) {
      setErrorMsg(err?.message || "Something went wrong. Please try again.");
      setStatus("error");
    }
  }

  if (status === "success") {
    return (
      <div className="auth-shell auth-shell-split login-layout">
        <aside className="auth-marketing auth-marketing-slab login-marketing">
          <div className="auth-wordmark">⚓ AnchorCV</div>
        </aside>
        <div className="auth-panel auth-form-card stack login-form">
          <div className="stack tight" style={{ textAlign: "center", paddingTop: "1rem" }}>
            <div style={{ fontSize: "2.8rem" }}>✅</div>
            <h2 className="page-title" style={{ margin: "0.5rem 0 0" }}>
              Password updated
            </h2>
            <p className="muted-copy" style={{ margin: "0.5rem 0 0" }}>
              Your new password has been saved. You can now sign in with your
              new credentials.
            </p>
            <button
              type="button"
              className="primary-button"
              style={{ marginTop: "1.25rem" }}
              onClick={() => navigate("/login")}
            >
              Sign in
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-shell auth-shell-split login-layout">
      <aside className="auth-marketing auth-marketing-slab login-marketing">
        <div className="auth-wordmark">⚓ AnchorCV</div>
        <div className="stack tight">
          <p className="eyebrow">Almost there</p>
          <h1
            className="auth-tagline"
            style={{ margin: 0, fontSize: "2.2rem", lineHeight: 1.1 }}
          >
            Choose a strong new password.
          </h1>
          <p className="muted-copy" style={{ margin: 0, maxWidth: "36rem" }}>
            At least 8 characters. Once saved you'll be taken straight to the
            sign-in page.
          </p>
        </div>
      </aside>

      <div className="auth-panel auth-form-card stack login-form">
        <div className="stack tight">
          <p className="eyebrow">Set new password</p>
          <h2 className="page-title" style={{ margin: 0 }}>
            Create your new password.
          </h2>
          <p className="muted-copy" style={{ margin: 0 }}>
            Enter your new password twice to confirm. The reset link is
            single-use and expires after 1 hour.
          </p>
        </div>

        <form className="stack" onSubmit={handleSubmit}>
          <div className="auth-password-row">
            <input
              type={showPassword ? "text" : "password"}
              placeholder="New password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
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

          <input
            type={showPassword ? "text" : "password"}
            placeholder="Confirm new password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
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
            {status === "loading" ? "Saving…" : "Update password"}
          </button>

          <button
            type="button"
            className="text-link-button"
            onClick={() => navigate("/login")}
          >
            ← Back to sign in
          </button>
        </form>
      </div>
    </div>
  );
}
