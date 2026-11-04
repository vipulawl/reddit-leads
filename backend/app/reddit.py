import argparse
import logging
import time
from datetime import datetime, timezone

import httpx

from .config import settings

log = logging.getLogger(__name__)
API = "https://oauth.reddit.com"
READABLE = {"public", "restricted"}


class Reddit:
    def __init__(self):
        self.client = httpx.Client(headers={"User-Agent": settings.reddit_user_agent}, timeout=20)
        self.token = None
        self.token_exp = 0.0

    def _auth(self):
        if self.token and time.time() < self.token_exp - 60:
            return
        r = self.client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(settings.reddit_client_id, settings.reddit_client_secret),
            data={"grant_type": "refresh_token", "refresh_token": settings.reddit_refresh_token}
            if settings.reddit_refresh_token else {"grant_type": "client_credentials"},
        )
        r.raise_for_status()
        data = r.json()
        self.token = data["access_token"]
        self.token_exp = time.time() + data["expires_in"]

    def get(self, path: str, **params) -> dict:
        self._auth()
        r = self.client.get(f"{API}{path}", params={"raw_json": 1, **params},
                            headers={"Authorization": f"Bearer {self.token}"})
        remaining = float(r.headers.get("x-ratelimit-remaining", 100))
        reset = float(r.headers.get("x-ratelimit-reset", 0))
        if remaining < 5:
            log.warning("Reddit rate limit low (%s left), sleeping %ss", remaining, reset)
            time.sleep(reset + 1)
        r.raise_for_status()
        return r.json()

    def new_posts(self, subs: list[str], limit: int = 100) -> list[dict]:
        return [normalize(c) for c in self.get(f"/r/{'+'.join(subs)}/new", limit=limit)["data"]["children"]]

    def new_comments(self, subs: list[str], limit: int = 100) -> list[dict]:
        return [normalize(c) for c in self.get(f"/r/{'+'.join(subs)}/comments", limit=limit)["data"]["children"]]

    def search(self, query: str, limit: int = 25, t: str = "day", sort: str = "new") -> list[dict]:
        data = self.get("/search", q=f'"{query}"', sort=sort, t=t, limit=limit, type="link")
        return [normalize(c) for c in data["data"]["children"]]

    def thread(self, post_id: str, limit: int = 15) -> tuple[dict, list[dict]]:
        post_listing, comment_listing = self.get(f"/comments/{post_id.removeprefix('t3_')}", limit=limit, depth=1, sort="top")
        post = normalize(post_listing["data"]["children"][0])
        comments = [
            c for c in (normalize(c) for c in comment_listing["data"]["children"] if c["kind"] == "t1")
            if c["author"] not in ("AutoModerator", "[deleted]") and c["body"] not in ("[removed]", "[deleted]")
        ]
        return post, comments

    def info(self, ids: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(ids), 100):
            out += [normalize(c) for c in self.get("/api/info", id=",".join(ids[i:i + 100]))["data"]["children"]]
        return out

    def subreddit_ok(self, name: str, min_subscribers: int = 0) -> str | None:
        try:
            data = self.get(f"/r/{name}/about")["data"]
        except (httpx.HTTPStatusError, KeyError):
            return None
        if data.get("subreddit_type") not in READABLE or data.get("over18"):
            return None
        if (data.get("subscribers") or 0) < min_subscribers:
            return None
        return data["display_name"]

    def search_subreddits(self, query: str, limit: int = 5, min_subscribers: int = 1000) -> list[tuple[str, int]]:
        children = self.get("/subreddits/search", q=query, limit=limit)["data"]["children"]
        return [
            (d["display_name"], d.get("subscribers") or 0)
            for d in (c["data"] for c in children)
            if d.get("subreddit_type") in READABLE and not d.get("over18") and (d.get("subscribers") or 0) >= min_subscribers
        ]


def source() -> str:
    if settings.reddit_source != "auto":
        return settings.reddit_source
    return "api" if settings.reddit_client_id and settings.reddit_client_secret else "rss"


def make_reddit():
    if source() == "rss":
        from .rss import RedditRSS
        return RedditRSS()
    return Reddit()


def normalize(child: dict) -> dict:
    d = child["data"]
    is_comment = child["kind"] == "t1"
    return {
        "id": d["name"],
        "kind": "comment" if is_comment else "post",
        "subreddit": d["subreddit"],
        "author": d.get("author", "[deleted]"),
        "title": d.get("link_title" if is_comment else "title", ""),
        "body": d.get("body" if is_comment else "selftext", "") or "",
        "permalink": "https://www.reddit.com" + d["permalink"],
        "posted_at": datetime.fromtimestamp(d["created_utc"], tz=timezone.utc),
        "post_id": d.get("link_id") if is_comment else d["name"],
        "num_comments": d.get("num_comments", 0),
        "score": d.get("score", 0),
        "removed": d.get("author") == "[deleted]" or bool(d.get("removed_by_category")),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sub", default="SaaS")
    p.add_argument("--limit", type=int, default=5)
    args = p.parse_args()
    for item in make_reddit().new_posts([args.sub], limit=args.limit):
        print(f"[{item['subreddit']}] {item['title'][:90]}  {item['permalink']}")
