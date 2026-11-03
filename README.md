# reddit-leads

**Enter your website URL, and reddit-leads finds people on Reddit who need what you sell, close to real time.**

Open source (AGPL-3.0). Self-host it free with your own keys, or use the hosted version (coming soon) with nothing to set up.

1. **Onboarding:** paste a URL. The app reads the homepage plus pricing/features/about pages and builds a profile: what the product does, who it's for, pain points, competitors, buyer phrases, and subreddits. It then checks every phrase against Reddit search (past year): phrases nobody uses are dropped, and subreddits are ranked by where matching posts actually appear. You review and edit before anything runs.
2. **Monitoring:** one shared worker polls new posts and comments in every watched subreddit, plus Reddit-wide keyword search, about every 60 seconds.
3. **Qualification:** a 3-stage funnel, cheapest stage first:
   | Stage | What | Cost |
   |---|---|---|
   | 1. Keyword match | exact phrase (or all its words in one sentence), no excluded keyword. Competitor names only count next to switching words ("alternative", "vs", "instead of"…) | free |
   | 2. Embedding filter | local `bge-small` embedding, cosine similarity to the project profile ≥ threshold | free (CPU, ms) |
   | 3. Intent | matches are grouped by thread (a matching comment pulls in its parent post), and each thread is judged once on the **original poster**, with its top replies as context. Self-promotion is caught by free text patterns first ("I built", "I work at", "disclosure", "N tools" listicles, webinars). Then yes/no questions: on topic? promoting? asking for a tool? has a specific problem? urgent? already answered by a reply? → a label, a 0–100 fit score, and a one-line reason. Uses [TypeSafe Jev](https://docs.typesafe.ai) if you have a key, otherwise any OpenAI-compatible LLM (local Ollama by default) | Jev: ~$0.04 / 1M input tokens. Ollama: free |
4. **Lead inbox:** one card per thread: the post on the left, replies on the right (comments that matched your keywords are outlined). Sorted best first: buyers before people with a problem, then fit, with a boost for unanswered and urgent threads and a penalty for already-answered and older ones. Filters for label, unanswered, burning problem, and not answered well. Reply counts refresh every few minutes; threads deleted on Reddit are removed.

   | Label | Meaning |
   |---|---|
   | 🔥 Hot · respond now | asking for a tool, recommendation, comparison, or alternative |
   | Warm · has the problem | describes the problem, not asking yet |
   | Show yours too | sharing or launching their own product in your space |
   | Discussion | on topic, not a lead (hidden by default) |
   | Irrelevant | keyword matched by coincidence (hidden) |

No accounts or login: it's a single-user, self-hosted app. Run it on your own machine or behind your own access control (VPN, basic auth at the proxy) if you put it on a server.

## Self-host vs hosted

| | Self-host | Hosted |
|---|---|---|
| Price | free (you pay your own API usage, which can be $0) | paid plan |
| Keys | your own Reddit app, plus Jev or an LLM | none |
| Runs | your machine or server | 24/7 on our servers |
| Reddit API | your own app, used for yourself, which fits Reddit's free non-commercial tier | handled by us |

## Architecture

```
web/ (Next.js) ──HTTP──> backend/ FastAPI (api)  ──┐
                                                    ├── Postgres (Docker) / SQLite (dev)
                         backend/ worker.py ────────┘
                           │  Reddit OAuth (app-only)   → new posts/comments + search
                           │  fastembed (local)         → embedding filter
                           │  Jev or OpenAI-compatible  → lead score
```

The worker fetches each subreddit **once for all users**, combining subreddits into multireddit requests (`/r/a+b+c/new`), then fans the posts out to every project watching them.

## What you need

| Key | Where | Required |
|---|---|---|
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → create app ("web app" or "script") | yes |
| `REDDIT_USER_AGENT` | `web:reddit-leads:v0.1 (by /u/yourname)` | yes |
| `REDDIT_REFRESH_TOKEN` | optional: log in as your Reddit user instead of app-only auth | no |
| `TYPESAFE_API_KEY` | [console.typesafe.ai](https://console.typesafe.ai) | no. Without it, scoring uses `SCORER_*` (Ollama by default) |
| `SCORER_BASE_URL` / `SCORER_API_KEY` / `SCORER_MODEL` | any OpenAI-compatible API. Defaults to local Ollama `llama3.2` | only if there's no Jev key |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | OpenAI (default `gpt-5-mini`), OpenRouter, or Ollama | yes, for onboarding |

**Fully free setup:** a Reddit app, no Jev key, with both `SCORER_*` and `LLM_*` pointed at Ollama (`ollama pull llama3.2`). Small local models score less reliably than Jev, so raise the min-score in the dashboard if you see noise.

## Run with Docker (recommended)

```zsh
git clone https://github.com/vipulawl/reddit-leads && cd reddit-leads
cp .env.example .env        # fill in keys
docker compose up -d --build
```

Open http://localhost:3000 and paste your URL.
- Uses Postgres in a container. Ollama on the host is reached via `host.docker.internal`.
- On a server, set `PUBLIC_API_URL=https://your-api-host` and `CORS_ORIGINS=https://your-web-host` before building.

## Run without Docker (development)

Requirements: Python 3.13, Node 20+.

```zsh
cp .env.example .env
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd web && npm install && cd ..

uvicorn backend.app.main:app --reload      # API on :8000
python -m backend.app.worker               # worker
cd web && npm run dev                      # dashboard on :3000
```

Quick checks:

```zsh
python -m backend.app.reddit --sub SaaS --limit 5                        # Reddit creds
python -m backend.app.scorer --text "any tool to find leads on reddit?"  # scorer (prints which backend)
python -m backend.app.onboarding https://example.com                      # profile generation
```

## Worker CLI flags

| Flag | Default | What |
|---|---|---|
| `--once` | off | run one poll cycle and exit |
| `--interval` | `60` | seconds between cycles |
| `--searches-per-cycle` | `5` | Reddit-wide keyword searches per cycle (round-robin across all projects) |
| `--max-score-per-cycle` | `50` | cap on new threads scored per cycle (cost guard) |
| `--score-workers` | `4` | parallel thread fetch + scoring calls (local Ollama runs them one at a time anyway) |
| `--refresh-every` | `5` | refresh reply counts every N cycles (1 Reddit call per 100 leads) |
| `--dry-run` | off | run stages 1–2, log what would be scored, skip scoring and don't save leads |

Threads older than 7 days are not turned into new leads.

**Re-label existing leads** after changing the prompt or model (one LLM call per thread, keeps replied/skipped status):

```zsh
python -m backend.app.rescore --project 7 --limit 5   # try a few first
python -m backend.app.rescore --project 7             # all threads
python -m backend.app.rescore --dry-run               # just count
```

Per-project settings, editable in the dashboard: keywords, excluded keywords, subreddits, similarity threshold (default `0.55`), and minimum lead score (default `60`).

## Costs / API usage

| Item | Usage | Cost |
|---|---|---|
| Reddit API | free tier is ~100 req/min per client ID. Each cycle uses 2 requests per 50 subreddits + `--searches-per-cycle` | $0 for personal use. Commercial use needs Reddit's approval |
| Embeddings | local `BAAI/bge-small-en-v1.5` (~65MB download on first run) | $0 |
| Thread fetch | 1 Reddit call per new thread that passes stages 1–2 | free (counts toward Reddit's rate limit) |
| Scoring: Jev | once per thread, ~1.5k tokens with replies | ≈ $0.50/month per active project |
| Scoring: `gpt-4o-mini` | once per thread, ~1.5k tokens in, ~100 out | ≈ $0.0003/thread, ~$1–3/month at 100–300 threads/day |
| Scoring: Ollama | runs locally, ~1.5k tokens per thread | $0 (needs a machine that can run a 3B model) |
| Onboarding LLM | one call per project, ~5k tokens, plus ~35 Reddit searches | < $0.01 with `gpt-5-mini`, $0 with Ollama |

**Model quality** (18 real threads, hand-labelled by what the original poster wants):

| Scorer | Correct label | Real leads kept | Non-leads shown as leads |
|---|---|---|---|
| `gpt-4o-mini` | 17/18 | 6/6 | 1 |
| `llama3.2` (3B) | 9/18 | 5/6 | 5 |

Onboarding with `llama3.2` also gives generic keywords and misses competitors. For good results use an OpenAI model for both `LLM_*` (onboarding) and `SCORER_*` (labelling); together that's a few dollars a month.

## File structure

```
reddit-leads/
├── backend/app/
│   ├── config.py       env settings
│   ├── db.py           SQLAlchemy engine/session
│   ├── models.py       User, Project, Lead
│   ├── auth.py         single local user (no login)
│   ├── main.py         FastAPI routes
│   ├── reddit.py       Reddit OAuth client (app-only), rate-limit aware
│   ├── onboarding.py   website → product profile (LLM), checked against Reddit search
│   ├── filters.py      stage 1 keyword match + stage 2 embedding filter
│   ├── scorer.py       stage 3 intent label + fit: Jev or OpenAI-compatible LLM
│   ├── threads.py      thread → lead: fetch post + replies, score, store
│   ├── rescore.py      re-label existing leads, one per thread
│   └── worker.py       poll → filter → group by thread → score → save loop
├── web/                Next.js dashboard (landing page, projects, lead inbox)
├── Dockerfile          backend image (api + worker)
├── docker-compose.yml  db + api + worker + web
├── requirements.txt
└── .env.example
```

## Roadmap
- Telegram and email alerts for hot leads
- AI reply drafts (optional)
- Hosted version with plans

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License
[AGPL-3.0](LICENSE). You can use, modify and self-host it freely. If you run a modified version as a network service, you must publish your changes under the same license.
