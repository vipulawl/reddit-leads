import argparse
import logging
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from . import filters
from .db import SessionLocal, init_db
from .models import Lead, Project
from .reddit import Reddit
from .scorer import score_item

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
        self.reddit = Reddit()
        self.http = httpx.Client(timeout=20)
        self.seen = SeenCache()
        self.search_cursor = 0

    def cycle(self):
        with SessionLocal() as db:
            projects = db.scalars(select(Project).where(Project.active, Project.profile_embedding.is_not(None))).all()
            if not projects:
                log.info("no active projects")
                return
            items = self.fetch(projects)
            candidates = self.filter(items, projects)
            self.score_and_save(db, candidates)

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
                if hits := filters.keyword_match(text, p.keywords, p.negative_keywords):
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
        fresh = [
            c for c in candidates
            if not db.scalar(select(Lead.id).where(Lead.project_id == c[1].id, Lead.reddit_id == c[0]["id"]))
        ]
        fresh.sort(key=lambda c: c[3], reverse=True)
        if len(fresh) > self.args.max_score_per_cycle:
            log.warning("capping Jev calls at %d (had %d)", self.args.max_score_per_cycle, len(fresh))
            fresh = fresh[: self.args.max_score_per_cycle]
        if self.args.dry_run:
            for item, p, hits, sim in fresh:
                log.info("[dry-run] would score p%d sim=%.2f %s | %s", p.id, sim, hits, item["title"][:80])
            return

        def run(c):
            item, p, _, _ = c
            try:
                return score_item(item, {"name": p.name, "description": p.description, "ideal_customer": p.icp}, self.http)
            except (httpx.HTTPError, KeyError, ValueError) as e:
                log.warning("Jev scoring failed for %s: %s", item["id"], e)
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(run, fresh))
        tokens = 0
        for (item, p, hits, sim), res in zip(fresh, results):
            if res is None:
                continue
            tokens += res["usage"].get("input_tokens", 0)
            db.add(Lead(
                project_id=p.id, reddit_id=item["id"], kind=item["kind"], subreddit=item["subreddit"],
                author=item["author"], title=item["title"], body=item["body"][:5000], permalink=item["permalink"],
                matched_keywords=hits, similarity=sim, intent_level=res["intent_level"],
                vendor_prob=res["vendor_prob"], score=res["score"], posted_at=item["posted_at"],
            ))
            log.info("lead p%d score=%d sim=%.2f %s", p.id, res["score"], sim, item["permalink"])
        db.commit()
        log.info("scored %d items, ~%d Jev input tokens", sum(r is not None for r in results), tokens)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--searches-per-cycle", type=int, default=5)
    p.add_argument("--max-score-per-cycle", type=int, default=50)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
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
