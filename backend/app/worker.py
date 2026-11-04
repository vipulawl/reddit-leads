import argparse
import logging
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from . import filters
from .examples import load_corrections
from .db import SessionLocal, init_db
from .models import Lead, Project
from .reddit import make_reddit, source
from .scorer import backend as scorer_backend
from .threads import build_lead, comment_out, merge_matches

log = logging.getLogger("worker")
SUBS_PER_REQUEST = 50
MAX_AGE = timedelta(hours=24)


class SeenCache:
    def __init__(self, size: int = 50_000):
        self.items: OrderedDict[str, None] = OrderedDict()
        self.size = size

    def add(self, key: str) -> bool:
        if key in self.items:
            return False
        self.items[key] = None
        if len(self.items) > self.size:
            self.items.popitem(last=False)
        return True


class Worker:
    def __init__(self, args):
        self.args = args
        self.reddit = make_reddit()
        self.http = httpx.Client(timeout=120)
        self.seen = SeenCache()
        self.search_cursor = 0
        self.cycles = 0

    def cycle(self):
        with SessionLocal() as db:
            projects = db.scalars(select(Project).where(Project.active, Project.profile_embedding.is_not(None))).all()
            if not projects:
                log.info("no active projects")
                return
            items = self.fetch(projects)
            candidates = self.filter(items, projects)
            self.score_and_save(db, candidates)
            self.cycles += 1
            if self.cycles % self.args.refresh_every == 0:
                self.refresh_counts(db)

    def fetch(self, projects: list[Project]) -> list[tuple[dict, list[Project]]]:
        by_sub: dict[str, list[Project]] = {}
        for p in projects:
            for s in p.subreddits:
                by_sub.setdefault(s.lower(), []).append(p)
        subs = sorted(by_sub)
        cutoff = datetime.now(timezone.utc) - MAX_AGE
        out: list[tuple[dict, list[Project]]] = []

        def keep(item, targets):
            if item["posted_at"] >= cutoff and item["author"] not in ("[deleted]", "AutoModerator") and self.seen.add(f"{item['id']}"):
                out.append((item, targets))

        for i in range(0, len(subs), SUBS_PER_REQUEST):
            chunk = subs[i:i + SUBS_PER_REQUEST]
            for fetcher in (self.reddit.new_posts, self.reddit.new_comments):
                try:
                    for item in fetcher(chunk):
                        keep(item, by_sub.get(item["subreddit"].lower(), []))
                except httpx.HTTPError as e:
                    log.warning("fetch failed for %d subs: %s", len(chunk), e)

        pairs = [(p, k) for p in projects for k in p.keywords]
        for _ in range(min(self.args.searches_per_cycle, len(pairs))):
            project, kw = pairs[self.search_cursor % len(pairs)]
            self.search_cursor += 1
            try:
                for item in self.reddit.search(kw):
                    if item["subreddit"].startswith("u_"):
                        continue
                    if self.seen.add(f"s:{project.id}:{item['id']}"):
                        if item["posted_at"] >= cutoff:
                            out.append((item, [project]))
            except httpx.HTTPError as e:
                log.warning("search failed for %r: %s", kw, e)
        log.info("fetched %d new items from %d subreddits", len(out), len(subs))
        return out

    def filter(self, items, projects) -> list[tuple[dict, Project, list[str], float]]:
        stage1 = []
        for item, targets in items:
            text = filters.item_text(item)
            for p in targets:
                if hits := filters.keyword_match(text, p.keywords, p.negative_keywords, p.competitors or []):
                    stage1.append((item, p, hits))
        unique = {it["id"]: filters.item_text(it) for it, _, _ in stage1}
        ids = list(unique)
        vecs = dict(zip(ids, filters.embed(list(unique.values()))))
        stage2 = []
        for item, p, hits in stage1:
            sim = filters.similarity(vecs[item["id"]], p.profile_embedding)
            if sim >= p.similarity_threshold:
                stage2.append((item, p, hits, sim))
        log.info("stage1 keyword: %d  stage2 embedding: %d", len(stage1), len(stage2))
        return stage2

    def score_and_save(self, db, candidates):
        groups: dict[tuple[int, str], dict] = {}
        for item, p, hits, sim in candidates:
            g = groups.setdefault((p.id, item["post_id"]), {"project": p, "matched": [], "hits": set(), "sim": 0.0})
            if item["kind"] == "comment":
                g["matched"].append(comment_out(item, max_chars=1500))
            g["hits"].update(hits)
            g["sim"] = max(g["sim"], sim)

        new = []
        for (project_id, post_id), g in groups.items():
            lead = db.scalar(select(Lead).where(Lead.project_id == project_id, Lead.reddit_id == post_id))
            if lead:
                merge_matches(lead, g["matched"], g["hits"])
            else:
                new.append((post_id, g))
        db.commit()

        new.sort(key=lambda x: x[1]["sim"], reverse=True)
        if len(new) > self.args.max_score_per_cycle:
            log.warning("capping scoring at %d threads (had %d)", self.args.max_score_per_cycle, len(new))
            new = new[: self.args.max_score_per_cycle]
        if self.args.dry_run:
            for post_id, g in new:
                log.info("[dry-run] would score p%d thread %s sim=%.2f %s", g["project"].id, post_id, g["sim"], sorted(g["hits"]))
            return

        corrections = {p.id: load_corrections(db, p.id, p.name) for p in {g["project"] for _, g in new}}

        def run(entry):
            post_id, g = entry
            try:
                return build_lead(self.reddit, self.http, g["project"], post_id, g["matched"], g["hits"], g["sim"],
                                  corrections=corrections[g["project"].id])
            except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
                log.warning("scoring failed for thread %s: %s", post_id, e)
                return None, {}

        with ThreadPoolExecutor(max_workers=self.args.score_workers) as pool:
            results = list(pool.map(run, new))
        tokens = 0
        for lead, usage in results:
            if lead is None:
                continue
            tokens += usage.get("input_tokens", 0)
            db.add(lead)
            log.info("lead p%d %s fit=%d replies=%d%s %s", lead.project_id, lead.intent, lead.score, lead.num_comments,
                     " urgent" if lead.urgent else "", lead.permalink)
        db.commit()
        log.info("scored %d threads with %s, ~%d input tokens", sum(l is not None for l, _ in results), scorer_backend(), tokens)

    def refresh_counts(self, db):
        since = datetime.now(timezone.utc) - timedelta(days=3)
        leads = db.scalars(select(Lead).where(Lead.status == "new", Lead.posted_at >= since,
                                              Lead.reddit_id.like("t3_%")).limit(500)).all()
        if not leads:
            return
        by_id = {l.reddit_id: l for l in leads}
        try:
            fresh = self.reddit.info(list(by_id))
        except httpx.HTTPError as e:
            log.warning("reply count refresh failed: %s", e)
            return
        removed = 0
        for item in fresh:
            lead = by_id.get(item["id"])
            if not lead:
                continue
            if item["removed"]:
                db.delete(lead)
                removed += 1
            else:
                lead.num_comments = item["num_comments"]
        db.commit()
        log.info("refreshed reply counts for %d leads, removed %d deleted on Reddit", len(fresh), removed)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=int, help="seconds between cycles (default: 60 with API keys, 300 with RSS)")
    p.add_argument("--searches-per-cycle", type=int, help="keyword searches per cycle (default: 5 with API keys, 1 with RSS)")
    p.add_argument("--max-score-per-cycle", type=int, default=50, help="max new threads scored per cycle")
    p.add_argument("--score-workers", type=int, default=4, help="parallel thread fetch + scoring calls")
    p.add_argument("--refresh-every", type=int, default=5, help="refresh reply counts every N cycles")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    rss = source() == "rss"
    args.interval = args.interval or (300 if rss else 60)
    if args.searches_per_cycle is None:
        args.searches_per_cycle = 1 if rss else 5
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    init_db()
    log.info("reading Reddit via %s", "public RSS feeds (no API keys)" if rss else "the Data API")
    worker = Worker(args)
    while True:
        started = time.time()
        try:
            worker.cycle()
        except Exception:
            log.exception("cycle failed")
        if args.once:
            break
        time.sleep(max(0, args.interval - (time.time() - started)))


if __name__ == "__main__":
    main()
