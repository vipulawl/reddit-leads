"use client";
import { useState } from "react";
import { api } from "@/lib/api";

export default function Login() {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { token } = await api(`/auth/${mode}`, { method: "POST", body: { email, password } });
      localStorage.setItem("token", token);
      window.location.href = "/projects";
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="narrow">
      <h1>reddit-leads</h1>
      <p className="muted">Enter your website. Get people on Reddit who need it.</p>
      <form onSubmit={submit} className="card stack">
        <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input type="password" placeholder="Password (8+ characters)" value={password}
          onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        {error && <p className="error">{error}</p>}
        <button disabled={busy}>{mode === "login" ? "Log in" : "Create account"}</button>
        <button type="button" className="link" onClick={() => setMode(mode === "login" ? "signup" : "login")}>
          {mode === "login" ? "No account? Sign up" : "Have an account? Log in"}
        </button>
      </form>
    </main>
  );
}
