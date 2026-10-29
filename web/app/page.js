"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const STEPS = [
  ["Paste your website", "We read your site and draft a profile: what you sell, who it's for, the pain points you solve, keywords, and subreddits to watch."],
  ["Review the setup", "Edit anything that's off, then start monitoring. Nothing runs until you approve it."],
  ["Get leads", "New posts and comments are checked about every minute, filtered, and scored for buying intent. The best ones land in your inbox."],
];

const PLANS = [
  {
    name: "Self-host",
    price: "Free",
    note: "You pay only your own API usage, which can be $0",
    points: [
      "Open source (AGPL-3.0), runs on your machine or server",
      "Bring your own Reddit app plus Jev or any OpenAI-compatible LLM",
      "Fully free option: Ollama for both onboarding and scoring",
      "Runs while your machine is on; you handle updates",
    ],
    cta: { label: "View on GitHub", href: "https://github.com/vipulawl/reddit-leads" },
  },
  {
    name: "Hosted",
    price: "Paid plan · coming soon",
    note: "Nothing to set up",
    points: [
      "No API keys, no Docker, no Reddit app",
      "Runs 24/7 on our servers, so you never miss a lead",
      "Reddit API access handled for you",
      "Automatic updates, nothing to maintain",
    ],
  },
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

      <section className="stack plans">
        <h2>Self-host or hosted?</h2>
        <p className="muted">
          reddit-leads is open source. If you&apos;re seeing this on localhost, you&apos;re already self-hosting.
          Pick self-host to stay free and keep everything on your machine, or hosted if you&apos;d rather not manage keys and servers.
        </p>
        <div className="grid">
          {PLANS.map((p) => (
            <div key={p.name} className="card stack plan">
              <div>
                <strong>{p.name}</strong>
                <div className="price">{p.price}</div>
                <div className="muted small">{p.note}</div>
              </div>
              <ul className="small">
                {p.points.map((pt) => <li key={pt}>{pt}</li>)}
              </ul>
              {p.cta && <a href={p.cta.href} target="_blank" rel="noreferrer" className="muted small">{p.cta.label} →</a>}
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
