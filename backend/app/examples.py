from collections.abc import Sequence
from functools import lru_cache

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import filters
from .models import Lead

PER_PROMPT = 3
OWN_BONUS = 0.1

INTENT_ANSWERS = {
    "buying": {"on_topic": True, "is_vendor": False, "asks_for_tool": True, "has_problem": True},
    "pain": {"on_topic": True, "is_vendor": False, "asks_for_tool": False, "has_problem": True},
    "showcase": {"on_topic": True, "is_vendor": True, "asks_for_tool": False, "has_problem": False},
    "discussion": {"on_topic": True, "is_vendor": False, "asks_for_tool": False, "has_problem": False},
    "irrelevant": {"on_topic": False, "is_vendor": False, "asks_for_tool": False, "has_problem": False},
}

# Made-up threads, so nothing from Reddit ships in the repo: (product, title, text, replies, intent, urgent, answered, fit)
SEEDS = [
    ("invoicing software for freelancers", "Freshbooks alternative that doesn't cost $30/month?",
     "Solo designer, 6 clients. Freshbooks just raised prices again. What are you all using for invoices?", [],
     "buying", False, False, 3),
    ("invoicing software for freelancers", "Clients keep paying 60 days late and I'm running out of cash",
     "Third month in a row. I send PDFs from Word and chase by email. Rent is due Friday.", ["have you tried late fees?"],
     "pain", True, False, 2),
    ("invoicing software for freelancers", "I made a free invoice generator after hating every tool, feedback welcome",
     "No signup, exports PDF, link below. Would love to hear what's missing.", ["looks clean"],
     "showcase", False, False, 1),
    ("invoicing software for freelancers", "Do you charge clients a late fee? What's normal?",
     "Curious how other freelancers handle this, percentage or flat fee?", ["2% a month", "never, it scares clients off"],
     "discussion", False, False, 1),
    ("CRM for small agencies", "Which agency would you hire to set up HubSpot for a 10-person team?",
     "We bought HubSpot and nobody uses it. Looking for someone to configure it or a simpler CRM.",
     ["we used a HubSpot partner called Northbeam, fixed it in two weeks"],
     "buying", False, True, 2),
    ("CRM for small agencies", "Are CRMs just a tax on sales teams now?",
     "Feels like every team I talk to hates their CRM. Is the whole category broken?", ["yes", "no, people just don't configure them"],
     "discussion", False, False, 1),
    ("CRM for small agencies", "What metric should agencies use to judge pipeline health?",
     "Win rate, pipeline velocity, something else? How do you think about it?", [],
     "discussion", False, False, 1),
    ("CRM for small agencies", "Lost a $20k deal because nobody followed up",
     "Our leads live in 4 spreadsheets and two inboxes. The client went with a competitor who replied same day. This keeps happening.", [],
     "pain", True, False, 3),
    ("project management tool", "We moved 40 people from Jira to our own tool, here's what we learned",
     "Long post. Our team built a lightweight tracker and we're opening it up, link in comments.", ["nice"],
     "showcase", False, False, 1),
    ("project management tool", "Why use Asana when you can just build it in Notion?",
     "Genuinely asking why people pay for PM tools when Notion templates do the same thing.", [],
     "discussion", False, False, 0),
    ("project management tool", "Trello vs ClickUp vs Linear for a 5-person dev team?",
     "Outgrowing Trello. Need sprints and GitHub integration, budget is tight.", ["Linear, no contest. We switched last year."],
     "buying", False, True, 3),
    ("project management tool", "Best way to keep sourdough starter alive while travelling?",
     "Going away two weeks and my task app reminders won't feed it lol", [],
     "irrelevant", False, False, 0),
    ("email marketing for online stores", "Klaviyo got too expensive at 15k subscribers, what did you switch to?",
     "Bill went from $150 to $400. Shopify store, mostly abandoned cart and welcome flows.", [],
     "buying", True, False, 3),
    ("email marketing for online stores", "How do you handle abandoned cart emails?",
     "Founder of CartPing here, we've seen 3 emails beat 1 by a mile. Happy to share templates, DM me.", [],
     "showcase", False, False, 1),
    ("email marketing for online stores", "Open rates dropped from 40% to 12% after switching domains",
     "Changed our sending domain last week and now everything lands in spam. Black Friday is in 10 days.",
     ["you need DMARC and to warm the new domain slowly, that fixed it for me"],
     "pain", True, True, 2),
    ("email marketing for online stores", "Everything we learned sending 2M emails this year",
     "Wrote up our subject line tests, send times and flows. Full write-up on our blog.", [],
     "showcase", False, False, 1),
    ("password manager for teams", "Need a password manager for a 12-person office",
     "The LastPass breach spooked us. Needs shared vaults and easy offboarding. 1Password or Bitwarden?", [],
     "buying", True, False, 3),
    ("password manager for teams", "Ex-employee still had access to our shared passwords sheet",
     "Found out a month after she left. We keep logins in a Google Sheet. How do I lock this down?", [],
     "pain", True, False, 3),
    ("password manager for teams", "Is it safe to keep passwords in the browser?",
     "Chrome keeps offering to save them. Is that actually fine in 2026?", ["fine for personal use"],
     "discussion", False, False, 1),
    ("website uptime monitoring", "Anything simpler than Datadog just to know when my site is down?",
     "Small SaaS, found out about an outage from a customer tweet. Just want an alert.", [],
     "buying", True, False, 3),
    ("website uptime monitoring", "Monitor recommendations for coding, 27 inch?",
     "Looking for a monitor for long coding sessions, budget around $300.", [],
     "irrelevant", False, False, 0),
    ("applicant tracking system", "Spending 10 hours a week copying candidates into spreadsheets",
     "We hire about 5 people a quarter. Every applicant goes into a sheet by hand and we still lose track.", [],
     "pain", False, False, 3),
    ("applicant tracking system", "I work at Greenhouse, AMA about hiring pipelines",
     "Happy to answer questions about structuring interviews and scorecards.", ["how do you handle referrals?"],
     "showcase", False, False, 1),
    ("meal planning app", "App that plans weekly meals around a gluten-free kid?",
     "Tired of planning every Sunday. Need something that builds a shopping list too.", [],
     "buying", False, False, 3),
    ("meal planning app", "Unpopular opinion: meal planning apps make cooking more stressful",
     "Every app wants me to log everything. I just cook what's in the fridge now.", ["same"],
     "discussion", False, False, 0),
]


def answer_for(intent: str, urgent: bool, answered: bool, fit: float) -> dict:
    lead = intent in ("buying", "pain")
    if intent == "irrelevant":
        fit = 0
    elif lead:
        fit = max(fit, 2)
    else:
        fit = min(fit, 1)
    return {**INTENT_ANSWERS[intent], "urgent": urgent and lead, "answered": answered, "fit": round(fit)}


def thread_text(title: str, body: str) -> str:
    return f"{title}\n{body[:500]}"


@lru_cache(maxsize=1)
def _seeds() -> tuple[list[dict], np.ndarray]:
    items = [{"product": product, "title": title, "text": text, "replies": replies,
              "answer": answer_for(intent, urgent, answered, fit)}
             for product, title, text, replies, intent, urgent, answered, fit in SEEDS]
    return items, filters.embed([thread_text(e["title"], e["text"]) for e in items])


def load_corrections(db: Session, project_id: int, product: str, limit: int = 200) -> list[dict]:
    leads = db.scalars(select(Lead).where(Lead.project_id == project_id, Lead.corrected_intent.is_not(None),
                                          Lead.embedding.is_not(None))
                       .order_by(Lead.created_at.desc()).limit(limit)).all()
    return [{"product": product, "title": l.title, "text": l.body[:400],
             "replies": [r["body"][:150] for r in (l.replies or [])[:2]],
             "answer": answer_for(l.corrected_intent, l.urgent, l.answered, l.intent_level), "vec": l.embedding}
            for l in leads]


def pick(title: str, body: str, corrections: Sequence[dict] = (), k: int = PER_PROMPT) -> list[dict]:
    vec = filters.embed([thread_text(title, body)])[0]
    seeds, seed_vecs = _seeds()
    scored = [(float(s), e) for s, e in zip(seed_vecs @ vec, seeds)]
    if corrections:
        own = np.asarray([c["vec"] for c in corrections], dtype=np.float32)
        scored += [(float(s) + OWN_BONUS, c) for s, c in zip(own @ vec, corrections)]
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:k]]
