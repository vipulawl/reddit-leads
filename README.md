# reddit-leads

**Enter your website URL, and reddit-leads finds people on Reddit who need what you sell, close to real time.**

Open source (AGPL-3.0). Self-host it free with your own keys, or use the hosted version (coming soon) with nothing to set up.

1. **Onboarding:** paste a URL. The app reads the site and builds a profile: what the product does, who it's for, the pain points it solves, keywords people use, and subreddits to watch. You can edit all of it.
2. **Monitoring:** one shared worker polls new posts and comments in every watched subreddit, plus Reddit-wide keyword search, about every 60 seconds.
3. **Qualification:** a 3-stage funnel, cheapest stage first:
   | Stage | What | Cost |
   |---|---|---|
   | 1. Keyword match | post contains a project keyword (exact phrase, or all its words) and no excluded keyword | free |
   | 2. Embedding filter | local `bge-small` embedding, cosine similarity to the project profile ≥ threshold | free (CPU, ms) |
   | 3. Lead scoring | buying-intent level + "is this a vendor promoting themselves?" → 0–100 score. Uses [TypeSafe Jev](https://docs.typesafe.ai) if you have a key, otherwise any OpenAI-compatible LLM (local Ollama by default) | Jev: ~$0.04 / 1M input tokens. Ollama: free |
4. **Lead inbox:** web dashboard, refreshes every 10s, sorted by score. Open on Reddit, mark replied or skip.

Supports multiple users (email + password accounts, each with their own projects).

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
| `JWT_SECRET` | any long random string (`openssl rand -hex 32`) | yes |

**Fully free setup:** a Reddit app, no Jev key, with both `SCORER_*` and `LLM_*` pointed at Ollama (`ollama pull llama3.2`). Small local models score less reliably than Jev, so raise the min-score in the dashboard if you see noise.

## Run with Docker (recommended)

```zsh
git clone https://github.com/vipulawl/reddit-leads && cd reddit-leads
cp .env.example .env        # fill in keys
docker compose up -d --build
```

Open http://localhost:3000, sign up, and paste your URL.
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
| `--max-score-per-cycle` | `50` | cap on scoring calls per cycle (cost guard) |
| `--dry-run` | off | run stages 1–2, log what would be scored, skip scoring and don't save leads |

Per-project settings, editable in the dashboard: keywords, excluded keywords, subreddits, similarity threshold (default `0.55`), and minimum lead score (default `60`).

## Costs / API usage

| Item | Usage | Cost |
|---|---|---|
| Reddit API | free tier is ~100 req/min per client ID. Each cycle uses 2 requests per 50 subreddits + `--searches-per-cycle` | $0 for personal use. Commercial use needs Reddit's approval |
| Embeddings | local `BAAI/bge-small-en-v1.5` (~65MB download on first run) | $0 |
| Scoring: Jev | only posts that pass stages 1–2, about 500 tokens each | ≈ $0.50/month per active project |
| Scoring: Ollama | runs locally | $0 (needs a machine that can run a 3B model) |
| Onboarding LLM | one call per project, ~4k tokens | < $0.01 with `gpt-5-mini`, $0 with Ollama |

## File structure

```
reddit-leads/
├── backend/app/
│   ├── config.py       env settings
│   ├── db.py           SQLAlchemy engine/session
│   ├── models.py       User, Project, Lead
│   ├── auth.py         signup/login, scrypt password hashing, JWT
│   ├── main.py         FastAPI routes
│   ├── reddit.py       Reddit OAuth client (app-only), rate-limit aware
│   ├── onboarding.py   website → product profile (LLM) + subreddit validation
│   ├── filters.py      stage 1 keyword match + stage 2 embedding filter
│   ├── scorer.py       stage 3 scoring: Jev or OpenAI-compatible LLM
│   └── worker.py       poll → filter → score → save loop
├── web/                Next.js dashboard (login, projects, lead inbox)
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
