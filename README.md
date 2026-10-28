# reddit-leads

Enter your website URL, and reddit-leads finds people on Reddit who need what you sell, close to real time.

1. **Onboarding:** paste a URL. The app reads the site and builds a profile: what the product does, who it's for, the pain points it solves, keywords people use, and subreddits to watch. You can edit all of it.
2. **Monitoring:** one shared worker polls new posts and comments in every watched subreddit, plus Reddit-wide keyword search, about every 60 seconds.
3. **Qualification:** a 3-stage funnel, cheapest stage first:
   | Stage | What | Cost |
   |---|---|---|
   | 1. Keyword match | post must mention a project keyword and no excluded keyword | free |
   | 2. Embedding filter | local `bge-small` embedding, cosine similarity to the project profile ≥ threshold | free (CPU, ms) |
   | 3. Jev scoring | [TypeSafe Jev](https://docs.typesafe.ai) decision model: buying-intent level + "is this a vendor promoting themselves?" → 0–100 lead score | ~$0.04 / 1M input tokens |
4. **Lead inbox:** web dashboard, refreshes every 10s, sorted by score. Open on Reddit, mark replied or skip.

Multi-user from day one (email + password accounts, each user has their own projects).

## Architecture

```
web/ (Next.js) ──HTTP──> backend/ FastAPI (api)  ──┐
                                                    ├── SQLite (dev) / Postgres (prod)
                         backend/ worker.py ────────┘
                           │  Reddit OAuth (app-only)   → new posts/comments + search
                           │  fastembed (local)         → embedding filter
                           │  TypeSafe Jev              → lead score
```

The worker fetches each subreddit **once for all users**, combining subreddits into multireddit requests (`/r/a+b+c/new`), then fans the posts out to every project watching them. The Reddit request count grows with the number of distinct subreddits, not with users.

## Setup

Requirements: Python 3.13, Node 20+.

```zsh
cd reddit-leads
cp .env.example .env            # fill in keys (see below)

# backend
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# frontend
cd web && npm install && cd ..
```

### Keys (`.env`)

| Var | Where to get it | Required |
|---|---|---|
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | reddit.com/prefs/apps (web app or script app) | yes |
| `REDDIT_USER_AGENT` | `web:reddit-leads:v0.1 (by /u/yourname)` | yes |
| `TYPESAFE_API_KEY` | console.typesafe.ai | yes (stage 3) |
| `LLM_API_KEY` | OpenAI, or any OpenAI-compatible provider (set `LLM_BASE_URL`, e.g. OpenRouter) | yes (onboarding only) |
| `JWT_SECRET` | any long random string | yes |
| `DATABASE_URL` | defaults to `sqlite:///./data/leads.db` | no |

## Run

Three processes:

```zsh
# 1. API (http://localhost:8000)
source .venv/bin/activate
uvicorn backend.app.main:app --reload

# 2. Worker (polls Reddit + qualifies)
python -m backend.app.worker                 # runs forever
python -m backend.app.worker --once          # one cycle, then exit (testing)

# 3. Dashboard (http://localhost:3000)
cd web && npm run dev
```

Quick checks without the UI:

```zsh
python -m backend.app.reddit --sub SaaS --limit 5        # test Reddit creds
python -m backend.app.scorer --text "any tool to find leads on reddit?"   # test Jev
python -m backend.app.onboarding https://example.com     # print generated profile
```

## Worker CLI flags

| Flag | Default | What |
|---|---|---|
| `--once` | off | run one poll cycle and exit |
| `--interval` | `60` | seconds between cycles |
| `--searches-per-cycle` | `5` | Reddit-wide keyword searches per cycle (round-robin across all projects) |
| `--max-score-per-cycle` | `50` | cap on Jev calls per cycle (cost guard) |
| `--dry-run` | off | run stages 1–2, log what would be scored, skip Jev and don't save leads |

Per-project settings, editable in the dashboard: keywords, excluded keywords, subreddits, similarity threshold (default `0.55`), and minimum lead score shown in the inbox (default `60`).

## Costs / API usage

| Item | Usage | Cost |
|---|---|---|
| Reddit API | free tier is ~100 req/min per client ID. Each cycle uses 2 requests per 50 subreddits + `--searches-per-cycle` | $0 (non-commercial). **A paid public product needs Reddit commercial approval.** |
| Embeddings | local `BAAI/bge-small-en-v1.5` via fastembed (~65MB download on first run) | $0 |
| Jev | only posts that pass stages 1–2. About 500 tokens per post → about 2,000 posts per $0.04 | ≈ $0.50/month for an active project |
| Onboarding LLM | one call per new project (`gpt-5-mini` by default, ~4k tokens) | < $0.01 per project |

## File structure

```
reddit-leads/
├── backend/app/
│   ├── config.py       env settings
│   ├── db.py           SQLAlchemy engine/session
│   ├── models.py       User, Project, Lead
│   ├── auth.py         signup/login, password hashing, JWT
│   ├── main.py         FastAPI routes
│   ├── reddit.py       Reddit OAuth client (app-only), rate-limit aware
│   ├── onboarding.py   website → product profile (LLM) + subreddit validation
│   ├── filters.py      stage 1 keyword match + stage 2 embedding filter
│   ├── scorer.py       stage 3 Jev scoring
│   └── worker.py       poll → filter → score → save loop
├── web/                Next.js dashboard (login, projects, lead inbox)
├── data/               SQLite db (gitignored)
├── requirements.txt
└── .env.example
```

## Not in v1
- AI reply drafts
- Telegram/email alerts
- Billing and plans
