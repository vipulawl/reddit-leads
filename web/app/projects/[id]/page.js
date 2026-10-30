"use client";
import { use, useEffect, useState } from "react";
import { api, timeAgo } from "@/lib/api";

export default function ProjectPage({ params }) {
  const { id } = use(params);
  const [project, setProject] = useState(null);
  const [tab, setTab] = useState("inbox");

  const loadProject = () =>
    api(`/projects/${id}`).then((p) => {
      setProject(p);
      if (p.ready && !p.active) setTab("setup");
    });

  useEffect(() => {
    loadProject();
    const t = setInterval(() => !project?.ready && loadProject(), 4000);
    return () => clearInterval(t);
  }, [id, project?.ready]);

  if (!project) return <main className="muted">Loading…</main>;
  const failed = project.description.startsWith("Setup failed");

  return (
    <main>
      <a href="/projects" className="muted small">← Projects</a>
      <header className="row between">
        <h1>{project.name}</h1>
        <nav className="row">
          <button className={tab === "inbox" ? "" : "ghost"} onClick={() => setTab("inbox")}>Leads</button>
          <button className={tab === "setup" ? "" : "ghost"} onClick={() => setTab("setup")}>Setup</button>
        </nav>
      </header>
      {failed ? (
        <div className="card stack">
          <p className="error">{project.description}</p>
          <button onClick={() => api(`/projects/${id}/regenerate`, { method: "POST" }).then(setProject)}>Retry setup</button>
        </div>
      ) : !project.ready ? (
        <div className="card">Reading {project.url} and picking keywords and subreddits… (about 30s)</div>
      ) : tab === "inbox" ? (
        <Inbox project={project} />
      ) : (
        <Setup
          project={project}
          onSaved={(p) => {
            setProject(p);
            if (p.active && !project.active) setTab("inbox");
          }}
        />
      )}
    </main>
  );
}

const INTENTS = {
  buying: { label: "🔥 Hot · respond now", tab: "Hot", hint: "They're choosing a tool right now. Reply with how your product solves it." },
  pain: { label: "Warm · has the problem", tab: "Warm", hint: "Help first. Mention your product only if it genuinely fits." },
  showcase: { label: "Show yours too", tab: "Show yours too", hint: "Someone is sharing their product here. Join in and show yours." },
  discussion: { label: "Discussion", tab: "Discussion", hint: "" },
};
const LEAD_TABS = ["buying", "pain", "showcase"];

function Inbox({ project }) {
  const [leads, setLeads] = useState([]);
  const [counts, setCounts] = useState({});
  const [status, setStatus] = useState("new");
  const [intent, setIntent] = useState("leads");
  const [minScore, setMinScore] = useState(project.min_score);

  const load = () => {
    const q = `status=${status}&min_score=${minScore}`;
    api(`/projects/${project.id}/leads?${q}&intent=${intent}`).then(setLeads);
    api(`/projects/${project.id}/lead-counts?${q}`).then(setCounts);
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [status, intent, minScore]);

  const leadTotal = LEAD_TABS.reduce((n, k) => n + (counts[k] || 0), 0);

  async function mark(lead, s) {
    await api(`/leads/${lead.id}`, { method: "PATCH", body: { status: s } });
    setLeads((ls) => (status === "all" ? ls.map((l) => (l.id === lead.id ? { ...l, status: s } : l)) : ls.filter((l) => l.id !== lead.id)));
  }

  return (
    <>
      <div className="row intents">
        <button className={intent === "leads" ? "chip active" : "chip"} onClick={() => setIntent("leads")}>All leads · {leadTotal}</button>
        {Object.entries(INTENTS).map(([k, v]) => (
          <button key={k} className={`chip ${intent === k ? "active" : ""}`} onClick={() => setIntent(k)}>
            {v.tab} · {counts[k] || 0}
          </button>
        ))}
      </div>
      <div className="row between small">
        <div className="row">
          {["new", "replied", "skipped", "all"].map((s) => (
            <button key={s} className={status === s ? "chip active" : "chip"} onClick={() => setStatus(s)}>{s}</button>
          ))}
        </div>
        <label className="row muted">
          min fit {minScore}
          <input type="range" min="0" max="100" step="5" value={minScore} onChange={(e) => setMinScore(+e.target.value)} />
        </label>
      </div>
      {leads.length === 0 && (
        <p className="muted">
          {intent === "leads"
            ? "No leads yet. The worker checks Reddit every minute, and new leads appear here automatically."
            : "Nothing here yet. Try another filter or lower the min fit."}
        </p>
      )}
      <div className="stack">
        {leads.map((l) => (
          <article key={l.id} className="card stack">
            <div className="row between small muted">
              <span>r/{l.subreddit} · u/{l.author} · {l.kind} · {timeAgo(l.posted_at)}</span>
              <span className={`score ${l.score >= 80 ? "hot" : ""}`} title="How well your product fits their need">fit {l.score}</span>
            </div>
            {INTENTS[l.intent] && (
              <div className="row">
                <span className={`intent intent-${l.intent}`}>{INTENTS[l.intent].label}</span>
                {l.reason && <span className="small muted">{l.reason}</span>}
              </div>
            )}
            <strong>{l.title}</strong>
            {l.body && <p className="body">{l.body.slice(0, 400)}{l.body.length > 400 ? "…" : ""}</p>}
            <div className="row small">
              {l.matched_keywords.map((k) => <span key={k} className="chip">{k}</span>)}
            </div>
            {l.status === "new" && INTENTS[l.intent]?.hint && <p className="small hint">{INTENTS[l.intent].hint}</p>}
            <div className="row">
              <a className="button" href={l.permalink} target="_blank" rel="noreferrer">Open on Reddit</a>
              {l.status !== "replied" && <button className="ghost" onClick={() => mark(l, "replied")}>Replied</button>}
              {l.status !== "skipped" && <button className="ghost" onClick={() => mark(l, "skipped")}>Skip</button>}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

const lines = (s) => s.split("\n").map((x) => x.trim()).filter(Boolean);

function Setup({ project, onSaved }) {
  const [f, setF] = useState({
    name: project.name,
    description: project.description,
    icp: project.icp,
    pain_points: project.pain_points.join("\n"),
    keywords: project.keywords.join("\n"),
    negative_keywords: project.negative_keywords.join("\n"),
    subreddits: project.subreddits.join("\n"),
    competitors: project.competitors.join("\n"),
    similarity_threshold: project.similarity_threshold,
    min_score: project.min_score,
    active: project.active,
  });
  const [msg, setMsg] = useState("");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function save(extra = {}) {
    const body = {
      ...f,
      ...extra,
      pain_points: lines(f.pain_points),
      keywords: lines(f.keywords),
      negative_keywords: lines(f.negative_keywords),
      subreddits: lines(f.subreddits),
      competitors: lines(f.competitors),
      similarity_threshold: +f.similarity_threshold,
      min_score: +f.min_score,
    };
    const saved = await api(`/projects/${project.id}`, { method: "PATCH", body });
    setF((prev) => ({ ...prev, active: saved.active }));
    onSaved(saved);
    setMsg("Saved");
    setTimeout(() => setMsg(""), 2000);
  }

  async function remove() {
    if (!window.confirm("Delete this project and all its leads?")) return;
    await api(`/projects/${project.id}`, { method: "DELETE" });
    window.location.href = "/projects";
  }

  const needsReview = !project.active;

  return (
    <div className="card stack">
      {needsReview && (
        <div className="banner">
          <strong>Review what we found</strong>
          <span className="small">
            We read {project.url}, checked which phrases people actually use on Reddit, and picked subreddits where those posts appear. Edit anything that's off, then start.
            Nothing is monitored until you confirm.
          </span>
        </div>
      )}
      <Field label="Name"><input value={f.name} onChange={set("name")} /></Field>
      <Field label="What it does"><textarea rows={2} value={f.description} onChange={set("description")} /></Field>
      <Field label="Ideal customer"><textarea rows={2} value={f.icp} onChange={set("icp")} /></Field>
      <div className="grid">
        <Field label="Pain points (one per line)"><textarea rows={5} value={f.pain_points} onChange={set("pain_points")} /></Field>
        <Field label="Competitors (helps spot people switching)"><textarea rows={5} value={f.competitors} onChange={set("competitors")} /></Field>
      </div>
      <div className="grid">
        <Field label="Keywords (one per line)"><textarea rows={10} value={f.keywords} onChange={set("keywords")} /></Field>
        <Field label="Excluded keywords"><textarea rows={10} value={f.negative_keywords} onChange={set("negative_keywords")} /></Field>
        <Field label="Subreddits"><textarea rows={10} value={f.subreddits} onChange={set("subreddits")} /></Field>
      </div>
      <div className="grid">
        <Field label={`Similarity threshold: ${f.similarity_threshold}`}>
          <input type="range" min="0.3" max="0.9" step="0.01" value={f.similarity_threshold} onChange={set("similarity_threshold")} />
        </Field>
        <Field label={`Min fit in inbox: ${f.min_score}`}>
          <input type="range" min="0" max="100" step="5" value={f.min_score} onChange={set("min_score")} />
        </Field>
        {!needsReview && (
          <label className="row"><input type="checkbox" checked={f.active} onChange={set("active")} /> Monitoring on</label>
        )}
      </div>
      <div className="row between">
        <div className="row">
          {needsReview ? (
            <>
              <button onClick={() => save({ active: true })}>Looks good — start finding leads</button>
              <button className="ghost" onClick={() => save()}>Save draft</button>
            </>
          ) : (
            <button onClick={() => save()}>Save</button>
          )}
          <span className="muted">{msg}</span>
        </div>
        <button className="danger" onClick={remove}>Delete project</button>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return <label className="field"><span className="small muted">{label}</span>{children}</label>;
}
