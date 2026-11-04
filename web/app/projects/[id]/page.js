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
const RELABEL = [["buying", "Hot: asking for a tool"], ["pain", "Warm: has the problem"], ["showcase", "Self-promotion"],
  ["discussion", "Just discussion"], ["irrelevant", "Not relevant"]];

function opportunity(l) {
  if (!["buying", "pain"].includes(l.intent)) return [];
  const tags = [];
  if (l.num_comments === 0) tags.push(["Unanswered", "opp-hot"]);
  else if (l.num_comments <= 3) tags.push([`Only ${l.num_comments} ${l.num_comments === 1 ? "reply" : "replies"}`, "opp-warm"]);
  if (l.urgent) tags.push(["Burning problem", "opp-hot"]);
  if (l.answered) tags.push(["Already answered", "opp-muted"]);
  return tags;
}

function hint(l) {
  if (l.status !== "new" || !INTENTS[l.intent]) return "";
  if (["buying", "pain"].includes(l.intent) && l.num_comments === 0) return "Nobody has replied yet. Be the first helpful answer.";
  if (l.answered) return "Others already recommended tools. Reply only if you add something they missed.";
  return INTENTS[l.intent].hint;
}

function Inbox({ project }) {
  const [leads, setLeads] = useState([]);
  const [counts, setCounts] = useState({});
  const [status, setStatus] = useState("new");
  const [intent, setIntent] = useState("leads");
  const [minScore, setMinScore] = useState(project.min_score);
  const [sort, setSort] = useState("best");
  const [only, setOnly] = useState("");

  const load = () => {
    const q = `status=${status}&min_score=${minScore}`;
    api(`/projects/${project.id}/leads?${q}&intent=${intent}&sort=${sort}`).then(setLeads);
    api(`/projects/${project.id}/lead-counts?${q}`).then(setCounts);
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [status, intent, minScore, sort]);

  const leadTotal = LEAD_TABS.reduce((n, k) => n + (counts[k] || 0), 0);
  const shown = leads.filter((l) =>
    only === "unanswered" ? l.num_comments === 0 : only === "urgent" ? l.urgent : only === "open" ? !l.answered : true);

  async function mark(lead, s) {
    await api(`/leads/${lead.id}`, { method: "PATCH", body: { status: s } });
    setLeads((ls) => (status === "all" ? ls.map((l) => (l.id === lead.id ? { ...l, status: s } : l)) : ls.filter((l) => l.id !== lead.id)));
  }

  async function refresh(lead) {
    const fresh = await api(`/leads/${lead.id}/refresh`, { method: "POST" });
    setLeads((ls) => ls.map((l) => (l.id === lead.id ? fresh : l)));
  }

  async function relabel(lead, label) {
    const fresh = await api(`/leads/${lead.id}/label`, { method: "POST", body: { intent: label } });
    setLeads((ls) => ls.map((l) => (l.id === lead.id ? fresh : l)));
    api(`/projects/${project.id}/lead-counts?status=${status}&min_score=${minScore}`).then(setCounts);
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
          {[["", "Any"], ["unanswered", "Unanswered"], ["urgent", "Burning problem"], ["open", "Not answered well"]].map(([k, label]) => (
            <button key={k} className={only === k ? "chip active" : "chip"} onClick={() => setOnly(k)}>{label}</button>
          ))}
        </div>
        <div className="row">
          {["new", "replied", "skipped", "all"].map((s) => (
            <button key={s} className={status === s ? "chip active" : "chip"} onClick={() => setStatus(s)}>{s}</button>
          ))}
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="best">Best first</option>
            <option value="new">Newest first</option>
          </select>
        </div>
      </div>
      <label className="row muted small">
        min fit {minScore}
        <input type="range" min="0" max="100" step="5" value={minScore} onChange={(e) => setMinScore(+e.target.value)} />
      </label>
      {shown.length === 0 && (
        <p className="muted">
          {intent === "leads" && !only
            ? "No leads yet. The worker checks Reddit every minute, and new leads appear here automatically."
            : "Nothing here yet. Try another filter or lower the min fit."}
        </p>
      )}
      <div className="stack">
        {shown.map((l) => <LeadCard key={l.id} lead={l} onMark={mark} onRefresh={refresh} onRelabel={relabel} />)}
      </div>
    </>
  );
}

function LeadCard({ lead: l, onMark, onRefresh, onRelabel }) {
  const [expanded, setExpanded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const long = l.body.length > 700;
  const tip = hint(l);

  async function refresh() {
    setRefreshing(true);
    try { await onRefresh(l); } finally { setRefreshing(false); }
  }

  return (
    <article className="card lead">
      <div className="stack lead-post">
        <div className="row between small muted">
          <span>r/{l.subreddit} · u/{l.author} · {timeAgo(l.posted_at)}</span>
          <span className={`score ${l.score >= 80 ? "hot" : ""}`} title="How well your product fits their need">fit {l.score}</span>
        </div>
        <div className="row">
          {INTENTS[l.intent] && <span className={`intent intent-${l.intent}`}>{INTENTS[l.intent].label}</span>}
          {opportunity(l).map(([label, cls]) => <span key={label} className={`opp ${cls}`}>{label}</span>)}
          <select className="relabel small" value="" onChange={(e) => e.target.value && onRelabel(l, e.target.value)}
            title="Your corrections become examples the scorer learns from">
            <option value="">{l.corrected ? "Corrected by you ✓" : "Wrong label?"}</option>
            {RELABEL.filter(([k]) => k !== l.intent).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </div>
        {l.reason && <span className="small muted">{l.reason}</span>}
        <strong>{l.title}</strong>
        {l.body && (
          <p className="body">
            {expanded || !long ? l.body : `${l.body.slice(0, 700)}…`}
            {long && <button className="link small" onClick={() => setExpanded(!expanded)}> {expanded ? "less" : "more"}</button>}
          </p>
        )}
        <div className="row small">
          {l.matched_keywords.map((k) => <span key={k} className="chip">{k}</span>)}
        </div>
        {tip && <p className="small hint">{tip}</p>}
        <div className="row">
          <a className="button" href={l.permalink} target="_blank" rel="noreferrer">Open on Reddit</a>
          {l.status !== "replied" && <button className="ghost" onClick={() => onMark(l, "replied")}>Replied</button>}
          {l.status !== "skipped" && <button className="ghost" onClick={() => onMark(l, "skipped")}>Skip</button>}
        </div>
      </div>
      <aside className="stack lead-replies">
        <div className="row between small">
          <strong>{l.num_comments} {l.num_comments === 1 ? "reply" : "replies"}</strong>
          {l.kind === "post" && (
            <button className="link small" disabled={refreshing} onClick={refresh}>{refreshing ? "Refreshing…" : "Refresh"}</button>
          )}
        </div>
        {l.matched_comments.map((c) => <Reply key={c.id} c={c} matched />)}
        {l.replies.filter((r) => !l.matched_comments.some((m) => m.id === r.id)).map((c) => <Reply key={c.id} c={c} />)}
        {l.num_comments === 0 && <p className="small muted">No replies yet.</p>}
        {l.num_comments > 0 && l.replies.length === 0 && l.matched_comments.length === 0 && (
          <p className="small muted">Replies not loaded. Hit Refresh.</p>
        )}
      </aside>
    </article>
  );
}

function Reply({ c, matched }) {
  return (
    <a className={`reply ${matched ? "matched" : ""}`} href={c.permalink} target="_blank" rel="noreferrer">
      <span className="small muted">
        u/{c.author}{c.score ? ` · ${c.score} pts` : ""}{matched ? " · matched your keywords" : ""}
      </span>
      <span className="small">{c.body.length > 280 ? `${c.body.slice(0, 280)}…` : c.body}</span>
    </a>
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
