import React, { useState } from "react";

export interface AuthUser {
  username: string;
  email: string;
  provider: "local" | "google" | "microsoft" | "guest";
  notifyEnabled: boolean;
  loggedInAt: string;
}

interface AuthLandingModalProps {
  onLoginSuccess: (user: AuthUser) => void;
  currentUser: AuthUser | null;
}

export const AuthLandingModal: React.FC<AuthLandingModalProps> = ({
  onLoginSuccess,
}) => {
  const [mode, setMode] = useState<"signin" | "register">("signin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [notifyEnabled, setNotifyEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showOauthNotice, setShowOauthNotice] = useState<string | null>(null);

  const handleLocalSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!username.trim()) {
      setError("Please enter a username.");
      return;
    }
    if (!password.trim() || password.length < 4) {
      setError("Password must be at least 4 characters.");
      return;
    }
    const resolvedEmail = email.trim() || (username.includes("@") ? username.trim() : `${username.trim()}@careerflow.local`);
    const user: AuthUser = {
      username: username.trim(),
      email: resolvedEmail,
      provider: "local",
      notifyEnabled,
      loggedInAt: new Date().toISOString(),
    };
    try {
      localStorage.setItem("careerflow.auth_user", JSON.stringify(user));
    } catch {
      // ignore storage quota errors
    }
    onLoginSuccess(user);
  };

  const handleOAuthLogin = (provider: "google" | "microsoft") => {
    setError(null);
    const providerName = provider === "google" ? "Google (Gmail)" : "Microsoft (Hotmail / Outlook)";
    const promptEmail = window.prompt(
      `Enter your ${providerName} email address to simulate OAuth sign-in for this session:`,
      provider === "google" ? "user@gmail.com" : "user@hotmail.com"
    );
    if (!promptEmail || !promptEmail.includes("@")) {
      return;
    }
    const derivedUser = promptEmail.split("@")[0] || "user";
    const user: AuthUser = {
      username: derivedUser,
      email: promptEmail.trim(),
      provider,
      notifyEnabled: true,
      loggedInAt: new Date().toISOString(),
    };
    try {
      localStorage.setItem("careerflow.auth_user", JSON.stringify(user));
    } catch {
      // ignore
    }
    setShowOauthNotice(
      `Authenticated via ${providerName} (${promptEmail}). Job notifications will be directed to this address.`
    );
    setTimeout(() => {
      onLoginSuccess(user);
    }, 600);
  };

  const handleLocalBypass = () => {
    const guestUser: AuthUser = {
      username: "Local Developer",
      email: "dev@careerflow.local",
      provider: "guest",
      notifyEnabled: false,
      loggedInAt: new Date().toISOString(),
    };
    try {
      localStorage.setItem("careerflow.auth_user", JSON.stringify(guestUser));
    } catch {
      // ignore
    }
    onLoginSuccess(guestUser);
  };

  return (
    <div className="auth-landing-overlay">
      <div className="auth-landing-card">
        {/* Header / Brand */}
        <div className="auth-brand-header">
          <div className="auth-logo-badge">⚡ CareerFlow</div>
          <h2 className="auth-title">Welcome to CareerFlow</h2>
          <p className="auth-subtitle">
            Autonomous Job Scraping, 80–85% ATS Calibration &amp; Resume Studio
          </p>
        </div>

        {/* Feature Badges */}
        <div className="auth-feature-pills">
          <span className="pill pill-blue">🎯 80–85% ATS Calibration</span>
          <span className="pill pill-green">🛡️ Locked Factual Guardrails</span>
          <span className="pill pill-purple">🔍 Multi-Portal Batch Scraper</span>
        </div>

        {/* OAuth Notice */}
        {showOauthNotice && (
          <div className="alert alert-success" style={{ margin: "14px 0", fontSize: 13 }}>
            ✓ {showOauthNotice}
          </div>
        )}

        {/* Error Alert */}
        {error && (
          <div className="alert alert-error" style={{ margin: "14px 0", fontSize: 13 }}>
            ✕ {error}
          </div>
        )}

        {/* Auth Mode Toggle Tabs */}
        <div className="auth-tab-switch">
          <button
            type="button"
            className={`auth-tab-btn ${mode === "signin" ? "active" : ""}`}
            onClick={() => {
              setMode("signin");
              setError(null);
            }}
          >
            Sign In
          </button>
          <button
            type="button"
            className={`auth-tab-btn ${mode === "register" ? "active" : ""}`}
            onClick={() => {
              setMode("register");
              setError(null);
            }}
          >
            Create Account
          </button>
        </div>

        {/* Login / Register Form */}
        <form onSubmit={handleLocalSubmit} className="auth-form stack-sm">
          <div>
            <label style={{ fontSize: 12 }}>Username or Email</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. gsvpramit or user@domain.com"
              autoFocus
            />
          </div>

          {mode === "register" && (
            <div>
              <label style={{ fontSize: 12 }}>Notification Email (Gmail / Hotmail / Custom)</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your.email@gmail.com"
              />
            </div>
          )}

          <div>
            <label style={{ fontSize: 12 }}>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </div>

          <label className="checkbox-row" style={{ marginTop: 6, fontSize: 12, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={notifyEnabled}
              onChange={(e) => setNotifyEnabled(e.target.checked)}
            />
            <span>Receive job alerts &amp; weekly session intelligence via email</span>
          </label>

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: "100%", marginTop: 8, padding: "10px", fontSize: 14 }}
          >
            {mode === "signin" ? "Sign In with Credentials" : "Create Account &amp; Continue"}
          </button>
        </form>

        {/* Divider */}
        <div className="auth-divider">
          <span>OR CONTINUE WITH</span>
        </div>

        {/* Social OAuth Buttons */}
        <div className="auth-oauth-buttons">
          <button
            type="button"
            className="btn-oauth btn-google"
            onClick={() => handleOAuthLogin("google")}
            title="Sign in with Google (Gmail)"
          >
            <svg width="18" height="18" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
              />
            </svg>
            Sign in with Google (Gmail)
          </button>

          <button
            type="button"
            className="btn-oauth btn-microsoft"
            onClick={() => handleOAuthLogin("microsoft")}
            title="Sign in with Microsoft (Hotmail / Outlook)"
          >
            <svg width="18" height="18" viewBox="0 0 24 24">
              <rect x="1" y="1" width="10" height="10" fill="#F25022" />
              <rect x="13" y="1" width="10" height="10" fill="#7FBA00" />
              <rect x="1" y="13" width="10" height="10" fill="#00A4EF" />
              <rect x="13" y="13" width="10" height="10" fill="#FFB900" />
            </svg>
            Sign in with Microsoft (Hotmail)
          </button>
        </div>

        {/* Local Dev Direct Access Bypass */}
        <div className="auth-dev-bypass">
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={handleLocalBypass}
            style={{ width: "100%", color: "var(--accent-blue)", fontSize: 13, border: "1px dashed rgba(10, 132, 255, 0.4)" }}
          >
            ⚡ Continue as Local Guest (Direct Dev Access)
          </button>
          <div className="small-note" style={{ textAlign: "center", marginTop: 4 }}>
            Local testing bypass &mdash; skips authentication for fast local workflow
          </div>
        </div>
      </div>
    </div>
  );
};
