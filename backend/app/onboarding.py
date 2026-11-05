import argparse
import json
import re
from collections import Counter
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from openai import BadRequestError, OpenAI

from .config import settings
from .reddit import make_reddit, source

PROMPT = """You are setting up Reddit lead monitoring for a business. The goal is to find Reddit posts written by people who could become customers of this exact product.

Read the website text and return JSON with:
- "name": product/business name
- "category": the product category in 2-5 words, the way a buyer would name it (e.g. "website analytics tool", "invoicing software for freelancers")
- "description": 1-2 sentences on what it does
- "icp": who the ideal customer is (role, company type, situation)
- "pain_points": 4-8 problems the customer has that this product solves, written in the customer's own words
- "competitors": 3-8 well-known products or services buyers compare this with or would switch away from. Real brand names only.
- "keywords": 15-25 lowercase phrases (2-5 words) that a potential buyer would literally write in a Reddit post when looking for this kind of product or struggling with the problem it solves.
- "negative_keywords": 3-8 lowercase phrases that signal an irrelevant post (job postings, courses, unrelated meanings of the keywords)
- "subreddits": 10-20 subreddit names (no r/ prefix) where the ideal customer asks for help or recommendations. Prefer niche communities of the ideal customer over generic startup/business subreddits.

Rules for keywords:
- Each keyword must point to THIS product category on its own, even read out of context.
- Include "alternative to <competitor>" style phrases, the category name, and how people describe the problem.
- Never use marketing copy, feature names, or generic phrases that appear in unrelated posts.
- Write real phrases with real names. Never output placeholders like <competitor>.
Example only, for an unrelated product (invoicing software for freelancers); do not reuse these:
Good: "freshbooks alternative", "invoicing app for freelancers", "clients paying invoices late", "quickbooks too expensive"
Bad: "billing dashboard", "free trial period", "payment integration", "financial reports"

Website: {url}

Website text:
{text}"""

LINK_HINTS = re.compile(r"pricing|feature|product|about|use-case|usecase|solution|why|how-it-works|compare|vs", re.I)


def _page_text(html: str, max_chars: int) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()
    parts = []
    if soup.title:
        parts.append(soup.title.get_text(strip=True))
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        parts.append(meta["content"])
    parts.append(soup.get_text(" ", strip=True))
    return "\n".join(parts)[:max_chars]


def fetch_site_text(url: str, max_chars: int = 12000, extra_pages: int = 3) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    http = httpx.Client(follow_redirects=True, timeout=20, headers={"User-Agent": "Mozilla/5.0 reddit-leads"})
    r = http.get(url)
    r.raise_for_status()
    home = str(r.url)
    host = urlparse(home).netloc
    links = []
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        link = urljoin(home, a["href"]).split("#")[0].rstrip("/")
        if urlparse(link).netloc == host and LINK_HINTS.search(urlparse(link).path) and link not in links:
            links.append(link)
    texts = [_page_text(r.text, 6000)]
    for link in links[:extra_pages]:
        try:
            page = http.get(link)
            if page.is_success:
                texts.append(f"--- {urlparse(link).path} ---\n" + _page_text(page.text, 2000))
        except httpx.HTTPError:
            continue
    return "\n\n".join(texts)[:max_chars]


def generate_profile(url: str, validate_subs: bool = True) -> dict:
    text = fetch_site_text(url)
    client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    for _ in range(3):
        resp = _complete(client, PROMPT.format(url=url, text=text))
        try:
            raw = json.loads(resp.choices[0].message.content)
        except json.JSONDecodeError:
            continue
        if _strings(raw.get("keywords")) and _strings(raw.get("subreddits")):
            break
    else:
        raise RuntimeError(f"{settings.llm_model} didn't return keywords and subreddits after 3 tries. Try a stronger LLM_MODEL.")
    competitors = _strings(raw.get("competitors"))[:8]
    category = _text(raw.get("category")).lower()
    keywords = [k.lower() for k in _strings(raw.get("keywords")) if _usable_keyword(k)]
    keywords = list(dict.fromkeys(([category] if category else []) + keywords))
    profile = {
        "name": _text(raw.get("name")),
        "description": _text(raw.get("description")),
        "icp": _text(raw.get("icp")),
        "pain_points": _strings(raw.get("pain_points")),
        "competitors": competitors,
        "keywords": keywords,
        "negative_keywords": [k.lower() for k in _strings(raw.get("negative_keywords"))],
    }
    subs = [s.removeprefix("/r/").removeprefix("r/").strip() for s in _strings(raw.get("subreddits"))]
    if validate_subs:
        searches = settings.rss_onboarding_searches if source() == "rss" else 30
        profile["keywords"], subs = ground_in_reddit(profile["keywords"], competitors, subs, max_searches=searches)
    profile["subreddits"] = subs
    return profile


def _complete(client: OpenAI, prompt: str):
    args = {"model": settings.llm_model, "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}}
    try:
        return client.chat.completions.create(**args, temperature=0.2)
    except BadRequestError as e:
        if "temperature" not in str(e):
            raise
        return client.chat.completions.create(**args)


def ground_in_reddit(keywords: list[str], competitors: list[str], suggested: list[str],
                     max_searches: int = 30, max_subs: int = 15) -> tuple[list[str], list[str]]:
    """Search Reddit's past year for each keyword and "<competitor> alternative": drop phrases
    nobody uses and rank subreddits by where matching posts actually appear."""
    reddit = make_reddit()
    try:
        reddit._auth()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Reddit login failed, check REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET in .env ({e})")
    evidence: Counter[str] = Counter()
    names: dict[str, str] = {}
    hits: dict[str, int] = {}
    searches = keywords[:max_searches] + [f"{c} alternative" for c in competitors[:min(5, max_searches)]]
    for kw in searches:
        try:
            posts = reddit.search(kw, limit=25, t="year", sort="relevance")
        except httpx.HTTPError:
            continue
        hits[kw] = len(posts)
        for post in posts:
            sub = post["subreddit"]
            if not sub.startswith("u_"):
                evidence[sub.lower()] += 1
                names[sub.lower()] = sub

    used = [k for k in keywords if hits.get(k, 1) > 0]
    if len(used) < 8:
        used = keywords

    suggested_lower = {s.lower() for s in suggested}
    candidates = {s.lower(): s for s in suggested}
    candidates.update({k: names[k] for k, n in evidence.items() if n >= 3})
    ranked = sorted(candidates, key=lambda k: -(evidence[k] + (3 if k in suggested_lower else 0)))
    subs = []
    for key in ranked:
        if len(subs) >= max_subs:
            break
        if key in suggested_lower and evidence[key] == 0 and len(subs) >= max_subs // 2:
            continue
        min_subs = 1000 if key in suggested_lower else 10_000
        if name := reddit.subreddit_ok(candidates[key], min_subscribers=min_subs):
            subs.append(name)
    if len(subs) < 5:
        found: dict[str, int] = {}
        for kw in used[:5]:
            try:
                found.update(reddit.search_subreddits(kw))
            except httpx.HTTPError:
                continue
        known = {s.lower() for s in subs}
        subs += [n for n, _ in sorted(found.items(), key=lambda x: -x[1]) if n.lower() not in known][: max_subs - len(subs)]
    if not subs:
        raise RuntimeError("None of the suggested subreddits exist or are public. Retry, or add subreddits manually in Setup.")
    return used, list(dict.fromkeys(subs))


EXAMPLE_KEYWORDS = {"freshbooks alternative", "invoicing app for freelancers", "clients paying invoices late",
                    "quickbooks too expensive", "billing dashboard", "free trial period", "payment integration",
                    "financial reports"}


def _usable_keyword(k: str) -> bool:
    return not re.search(r"[<>{}\[\]]", k) and k.lower().strip() not in EXAMPLE_KEYWORDS


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_text(v)}" for k, v in value.items())
    if isinstance(value, list):
        return "; ".join(_text(v) for v in value)
    return str(value).strip()


def _strings(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return []
    return [s for s in (_text(v) for v in value) if s]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--no-validate", action="store_true", help="skip Reddit keyword and subreddit validation")
    args = p.parse_args()
    print(json.dumps(generate_profile(args.url, validate_subs=not args.no_validate), indent=2))
