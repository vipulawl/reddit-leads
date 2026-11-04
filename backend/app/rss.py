import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .config import settings

log = logging.getLogger(__name__)
ATOM = {"a": "http://www.w3.org/2005/Atom"}
BASE = "https://www.reddit.com"
POST_IN_LINK = re.compile(r"/comments/([a-z0-9]+)/")
COMMENT_TITLE = re.compile(r"^/u/\S+ on ")


# Anonymous feeds allow about one request per rate-limit window, so all requests share one throttle.
class RedditRSS:

    lock = threading.Lock()
    next_at = 0.0

    def __init__(self):
        self.client = httpx.Client(headers={"User-Agent": settings.reddit_user_agent}, timeout=30, follow_redirects=True)
        self.checked: dict[str, str | None] = {}

    def _auth(self):
        pass

    def feed(self, path: str, **params) -> list[ET.Element]:
        for _ in range(3):
            with RedditRSS.lock:
                time.sleep(max(0.0, RedditRSS.next_at - time.time()))
                r = self.client.get(f"{BASE}{path}", params=params)
                reset = float(r.headers.get("x-ratelimit-reset", 0) or 0)
                remaining = float(r.headers.get("x-ratelimit-remaining", 1) or 0)
                wait = reset + 1 if remaining < 1 or r.status_code == 429 else 0
                RedditRSS.next_at = time.time() + max(wait, settings.reddit_rss_min_gap)
            log.debug("rss %s %d, next request in %.0fs", path, r.status_code, RedditRSS.next_at - time.time())
            if r.status_code != 429:
                break
            log.warning("Reddit RSS rate limited, retrying in %.0fs", wait)
        r.raise_for_status()
        return ET.fromstring(r.content).findall("a:entry", ATOM)

    def new_posts(self, subs: list[str], limit: int = 100) -> list[dict]:
        return [entry_out(e) for e in self.feed(f"/r/{'+'.join(subs)}/new/.rss", limit=limit)]

    def new_comments(self, subs: list[str], limit: int = 100) -> list[dict]:
        return [entry_out(e) for e in self.feed(f"/r/{'+'.join(subs)}/comments/.rss", limit=limit)]

    def search(self, query: str, limit: int = 25, t: str = "day", sort: str = "new") -> list[dict]:
        return [entry_out(e) for e in self.feed("/search.rss", q=f'"{query}"', sort=sort, t=t, limit=limit, type="link")]

    def thread(self, post_id: str, limit: int = 15) -> tuple[dict, list[dict]]:
        entries = [entry_out(e) for e in self.feed(f"/comments/{post_id.removeprefix('t3_')}/.rss",
                                                   limit=limit, depth=1, sort="top")]
        post = next(e for e in entries if e["kind"] == "post")
        comments = [c for c in entries if c["kind"] == "comment" and c["author"] not in ("AutoModerator", "[deleted]")
                    and c["body"] not in ("[removed]", "[deleted]")]
        post["num_comments"] = len(comments)
        return post, comments

    def info(self, ids: list[str]) -> list[dict]:
        return []

    def subreddit_ok(self, name: str, min_subscribers: int = 0) -> str | None:
        if name.lower() not in self.checked:
            try:
                entries = self.feed(f"/r/{name}/new/.rss", limit=1)
                self.checked[name.lower()] = entries[0].find("a:category", ATOM).get("term") if entries else None
            except (httpx.HTTPError, ET.ParseError, AttributeError):
                self.checked[name.lower()] = None
        return self.checked[name.lower()]

    def search_subreddits(self, query: str, limit: int = 5, min_subscribers: int = 1000) -> list[tuple[str, int]]:
        return []


def _text(entry: ET.Element, tag: str) -> str:
    el = entry.find(f"a:{tag}", ATOM)
    return (el.text or "") if el is not None else ""


def entry_out(entry: ET.Element) -> dict:
    rid = _text(entry, "id")
    is_comment = rid.startswith("t1_")
    link = entry.find("a:link", ATOM).get("href")
    category = entry.find("a:category", ATOM)
    author = _text(entry, "author/a:name").removeprefix("/u/") or "[deleted]"
    md = BeautifulSoup(_text(entry, "content"), "html.parser").find("div", class_="md")
    body = md.get_text("\n", strip=True) if md else ""
    title = _text(entry, "title")
    post = POST_IN_LINK.search(link)
    return {
        "id": rid,
        "kind": "comment" if is_comment else "post",
        "subreddit": category.get("term") if category is not None else "",
        "author": author,
        "title": COMMENT_TITLE.sub("", title) if is_comment else title,
        "body": body,
        "permalink": link,
        "posted_at": datetime.fromisoformat(_text(entry, "published") or _text(entry, "updated")),
        "post_id": f"t3_{post.group(1)}" if post else rid,
        "num_comments": 0,
        "score": 0,
        "removed": author == "[deleted]" or body in ("[removed]", "[deleted]"),
    }
