from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import httpx

from .models import Lead, Project
from .reddit import Reddit
from .scorer import MAX_REPLIES, score_thread

THREAD_MAX_AGE = timedelta(days=7)


def product_context(p: Project) -> dict:
    return {
        "name": p.name, "description": p.description, "ideal_customer": p.icp,
        "problems_solved": p.pain_points, "competitors": p.competitors or [],
    }


def comment_out(c: dict, max_chars: int = 600) -> dict:
    return {
        "id": c["id"], "author": c["author"], "body": c["body"][:max_chars], "score": c.get("score", 0),
        "permalink": c["permalink"], "posted_at": c["posted_at"].isoformat(),
    }


def merge_matches(lead: Lead, matched: list[dict], hits: set[str]):
    known = {c["id"] for c in lead.matched_comments or []}
    lead.matched_comments = (lead.matched_comments or []) + [c for c in matched if c["id"] not in known]
    lead.matched_keywords = sorted(set(lead.matched_keywords or []) | hits)


def build_lead(reddit: Reddit, http: httpx.Client, project: Project, post_id: str, matched: list[dict],
               hits: set[str], sim: float, max_age: timedelta = THREAD_MAX_AGE,
               corrections: Sequence[dict] = ()) -> tuple[Lead | None, dict]:
    post, replies = reddit.thread(post_id)
    if post["removed"] or post["posted_at"] < datetime.now(timezone.utc) - max_age:
        return None, {}
    res = score_thread(post, replies, product_context(project), http, corrections)
    lead = Lead(
        project_id=project.id, reddit_id=post_id, kind="post", subreddit=post["subreddit"], author=post["author"],
        title=post["title"], body=post["body"][:5000], permalink=post["permalink"], posted_at=post["posted_at"],
        matched_keywords=sorted(hits), similarity=sim, intent_level=res["intent_level"], vendor_prob=res["vendor_prob"],
        score=res["score"], intent=res["intent"], reason=res["reason"], urgent=res["urgent"], answered=res["answered"],
        num_comments=post["num_comments"],
        replies=[comment_out(r) for r in replies if r["author"] != post["author"]][:MAX_REPLIES],
        matched_comments=matched,
    )
    return lead, res["usage"]


def refresh_replies(reddit: Reddit, lead: Lead):
    post, replies = reddit.thread(lead.reddit_id)
    lead.num_comments = post["num_comments"]
    lead.replies = [comment_out(r) for r in replies if r["author"] != post["author"]][:MAX_REPLIES]
