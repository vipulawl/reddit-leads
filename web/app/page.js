"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const STEPS = [
  ["Paste your website", "We read your site and draft a profile: what you sell, who it's for, the pain points you solve, keywords, and subreddits to watch."],
  ["Review the setup", "Edit anything that's off, then start monitoring. Nothing runs until you approve it."],
  ["Get leads", "New posts and comments are checked about every minute, filtered, and scored for buying intent. The best ones land in your inbox."],
];

export default function Home() {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [projectCount, setProjectCount] = useState(0);

  useEffect(() => {
    api("/projects").then((p) => setProjectCount(p.length)).catch(() => {});
  }, []);

  async function start(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const p = await api("/projects", { method: "POST", body: { url } });
      window.location.href = `/projects/${p.id}`;
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <main className="landing">
      <header className="row between">
        <strong>reddit-leads</strong>
        {projectCount > 0 && <a href="/projects" className="muted small">Your projects ({projectCount}) →</a>}
      </header>

      <section className="hero stack">
        <h1>Find people on Reddit who need what you sell</h1>
        <p className="muted lead">
          Enter your website. reddit-leads watches Reddit in near real time and surfaces posts from people
          asking for exactly what you offer, scored by buying intent.
        </p>
        <form onSubmit={start} className="card row">
          <input placeholder="yourwebsite.com" value={url} onChange={(e) => setUrl(e.target.value)} required autoFocus />
          <button disabled={busy}>{busy ? "Starting…" : "Find leads"}</button>
        </form>
        {error && <p className="error">{error}</p>}
      </section>

      <section className="grid">
        {STEPS.map(([title, text], i) => (
          <div key={title} className="card stack step">
            <span className="muted small">Step {i + 1}</span>
            <strong>{title}</strong>
            <p className="muted small">{text}</p>
          </div>
        ))}
      </section>
    </main>
  );
}
