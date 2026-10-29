"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function Projects() {
  const [projects, setProjects] = useState(null);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");

  const load = () => api("/projects").then(setProjects).catch((e) => setError(e.message));

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  async function add(e) {
    e.preventDefault();
    setError("");
    try {
      const p = await api("/projects", { method: "POST", body: { url } });
      window.location.href = `/projects/${p.id}`;
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <main>
      <header className="row between">
        <h1>Your projects</h1>
        <a href="/" className="muted small">Home</a>
      </header>
      <form onSubmit={add} className="card row">
        <input placeholder="yourwebsite.com" value={url} onChange={(e) => setUrl(e.target.value)} required />
        <button>Find leads</button>
      </form>
      {error && <p className="error">{error}</p>}
      {projects?.length === 0 && <p className="muted">Add your website above to get started.</p>}
      <div className="stack">
        {projects?.map((p) => (
          <a key={p.id} href={`/projects/${p.id}`} className="card row between">
            <div>
              <strong>{p.name}</strong>
              <div className="muted small">{p.ready ? `${p.subreddits.length} subreddits · ${p.keywords.length} keywords` : "Setting up…"}</div>
            </div>
            {p.ready && !p.active ? (
              <span className="chip">Review setup</span>
            ) : (
              p.lead_count > 0 && <span className="badge">{p.lead_count} new</span>
            )}
          </a>
        ))}
      </div>
    </main>
  );
}
