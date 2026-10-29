import argparse
import json

import httpx
from bs4 import BeautifulSoup
from openai import OpenAI

from .config import settings
from .reddit import Reddit

PROMPT = """You are setting up Reddit lead monitoring for a business. From the website text below, return JSON with:
- "name": product/business name
- "description": 1-2 sentences on what it does
- "icp": who the ideal customer is (role, company type, situation)
- "pain_points": 4-8 problems the customer has that this product solves, written the way a customer would describe them
- "keywords": 10-20 short phrases (1-3 words) that a potential customer would actually type in a Reddit post when they have this problem or are looking for this kind of tool. Lowercase. Include category terms and competitor names. Avoid generic single words.
- "negative_keywords": 3-8 lowercase phrases that signal irrelevant posts (e.g. job postings, unrelated meanings of keywords)
- "subreddits": 10-20 subreddit names (no r/ prefix) where these customers ask for help or recommendations

Website: {url}

Website text:
{text}"""


def fetch_site_text(url: str, max_chars: int = 8000) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    r = httpx.get(url, follow_redirects=True, timeout=20, headers={"User-Agent": "Mozilla/5.0 reddit-leads"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    parts = []
    if soup.title:
        parts.append(soup.title.get_text(strip=True))
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        parts.append(meta["content"])
    parts.append(soup.get_text(" ", strip=True))
    return "\n".join(parts)[:max_chars]


def generate_profile(url: str, validate_subs: bool = True) -> dict:
    text = fetch_site_text(url)
    client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    for _ in range(3):
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": PROMPT.format(url=url, text=text)}],
            response_format={"type": "json_object"},
        )
        try:
            raw = json.loads(resp.choices[0].message.content)
        except json.JSONDecodeError:
            continue
        if _strings(raw.get("keywords")) and _strings(raw.get("subreddits")):
            break
    else:
        raise RuntimeError(f"{settings.llm_model} didn't return keywords and subreddits after 3 tries. Try a stronger LLM_MODEL.")
    profile = {
        "name": _text(raw.get("name")),
        "description": _text(raw.get("description")),
        "icp": _text(raw.get("icp")),
        "pain_points": _strings(raw.get("pain_points")),
        "keywords": [k.lower() for k in _strings(raw.get("keywords"))],
        "negative_keywords": [k.lower() for k in _strings(raw.get("negative_keywords"))],
    }
    subs = [s.removeprefix("r/").removeprefix("/r/").strip() for s in _strings(raw.get("subreddits"))]
    if validate_subs:
        reddit = Reddit()
        try:
            reddit._auth()
        except httpx.HTTPError as e:
            raise RuntimeError(f"Reddit login failed, check REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET in .env ({e})")
        subs = [name for s in subs if (name := reddit.subreddit_ok(s))]
        if not subs:
            raise RuntimeError("None of the suggested subreddits exist or are public. Retry, or add subreddits manually in Setup.")
    profile["subreddits"] = list(dict.fromkeys(subs))
    return profile


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
    p.add_argument("--no-validate", action="store_true", help="skip Reddit subreddit validation")
    args = p.parse_args()
    print(json.dumps(generate_profile(args.url, validate_subs=not args.no_validate), indent=2))
