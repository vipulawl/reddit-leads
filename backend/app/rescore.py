import argparse
import logging
import re
from datetime import timedelta

import httpx
from sqlalchemy import select

from .db import SessionLocal, init_db
from .examples import load_corrections
from .models import Lead, Project
from .reddit import make_reddit
from .scorer import backend as scorer_backend
from .threads import build_lead

log = logging.getLogger("rescore")
STATUS_RANK = {"replied": 2, "skipped": 1, "new": 0}
POST_ID = re.compile(r"/comments/([a-z0-9]+)/")


def thread_id(lead: Lead) -> str | None:
    if lead.reddit_id.startswith("t3_"):
        return lead.reddit_id
    m = POST_ID.search(lead.permalink)
    return f"t3_{m.group(1)}" if m else None


def rescore(project: Project, db, dry_run: bool, limit: int | None):
    groups: dict[str, list[Lead]] = {}
    for lead in db.scalars(select(Lead).where(Lead.project_id == project.id)):
        if tid := thread_id(lead):
            groups.setdefault(tid, []).append(lead)
    items = list(groups.items())[:limit]
    log.info("project %d: %d leads in %d threads, rescoring %d with %s", project.id,
             sum(len(v) for v in groups.values()), len(groups), len(items), scorer_backend())
    if dry_run:
        return
    reddit, http = make_reddit(), httpx.Client(timeout=120)
    corrections = load_corrections(db, project.id, project.name)
    for tid, old in items:
        matched = [{"id": l.reddit_id, "author": l.author, "body": l.body[:1500], "score": 0, "permalink": l.permalink,
                    "posted_at": l.posted_at.isoformat()} for l in old if l.kind == "comment"]
        hits = {k for l in old for k in l.matched_keywords}
        try:
            new, _ = build_lead(reddit, http, project, tid, matched, hits, max(l.similarity for l in old),
                                max_age=timedelta(days=365), corrections=corrections)
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
            log.warning("skipping %s: %s", tid, e)
            continue
        for l in old:
            db.delete(l)
        db.flush()
        if new:
            new.status = max((l.status for l in old), key=lambda s: STATUS_RANK.get(s, 0))
            if fixed := next((l for l in old if l.corrected_intent), None):
                new.intent, new.corrected_intent, new.embedding = fixed.corrected_intent, fixed.corrected_intent, fixed.embedding
            db.add(new)
            log.info("%s %-10s fit=%3d replies=%3d (was %d cards) %s", tid, new.intent, new.score, new.num_comments,
                     len(old), new.title[:60])
        else:
            log.info("%s removed on Reddit, dropped %d cards", tid, len(old))
        db.commit()


def main():
    p = argparse.ArgumentParser(description="Merge per-comment leads into one lead per thread and re-label them")
    p.add_argument("--project", type=int, help="project id (default: all)")
    p.add_argument("--limit", type=int, help="max threads per project")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    init_db()
    with SessionLocal() as db:
        q = select(Project)
        if args.project:
            q = q.where(Project.id == args.project)
        for project in db.scalars(q).all():
            rescore(project, db, args.dry_run, args.limit)


if __name__ == "__main__":
    main()
