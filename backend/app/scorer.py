import argparse
import json
import logging
import re
from collections.abc import Sequence

import httpx

from . import examples as fewshot
from .config import settings

log = logging.getLogger(__name__)
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
INTENTS = ("buying", "pain", "showcase", "discussion", "irrelevant")
MAX_REPLIES = 8
PROMPT_REPLIES = 5
PROMPT_CHARS = 1500

FIT_LEVELS = [
    "This product would not help the author",
    "Loosely related; the product might help a little",
    "The product clearly addresses the author's situation",
    "The author is describing exactly what this product does",
]

QUESTIONS = {
    "on_topic": "Is the post about the same problem space as the product, rather than a keyword that matched by coincidence?",
    "is_vendor": "Is the AUTHOR promoting something: they say they built, run, work at, or sell a product, service or agency; share their own brand or link; post a guide, case study, or 'N tools/ways' list; or promote an event, webinar, newsletter, or report?",
    "asks_for_tool": "Is the AUTHOR personally asking others to recommend, compare, or choose a tool, service, agency, or alternative for their own use? Rhetorical questions and questions inside a guide don't count.",
    "has_problem": "Does the AUTHOR describe a specific problem they personally have right now that the product would solve? General industry observations, opinions, and discussion prompts like 'are we all ignoring X?' don't count.",
    "urgent": "Is that problem urgent or costly for the author right now: losing money, traffic or customers, a deadline, already tried things that failed, or clearly frustrated?",
    "answered": "Do the replies already solve the author's problem or recommend a specific product? false if there are no replies.",
}

LLM_PROMPT = """You check whether a Reddit thread is a sales lead for a product. Judge only the ORIGINAL POSTER (the author of the post), not the people replying.

"reason": one short sentence (max 20 words) on what the original poster wants.
{questions}
"fit": how well the product fits the original poster's need:
{levels}

Solved examples from other threads:
{examples}

Now this thread.
Product: {product}

Post in r/{subreddit} by u/{author}, {num_comments} replies so far:
Title: {title}
Text: {text}

Top replies:
{replies}

Return only JSON: {{"reason": "<sentence>", {question_keys}, "fit": <0-3>}}"""

PROMO_PATTERNS = [re.compile(p, re.I) for p in (
    r"\bi (?:built|made|created|launched|developed|shipped) (?:a|an|my|this|our)?\s?[\w\s-]{0,30}?(?:tool|app|product|extension|plugin|saas|platform|checker|tracker|dashboard|service|bot)\b",
    r"\bwe(?:'ve| have)? (?:built|launched|shipped|released)\b",
    r"\bi work (?:at|for) (?:a|an)\b",
    r"\bdisclosure\b",
    r"\b(?:my|our) (?:tool|app|product|startup|saas|platform|extension|newsletter)\b",
    r"\b(?:co-?founder|founder|ceo) (?:of|at|here)\b",
    r"\b(?:webinar|live session|live q&a|register here|sign up here)\b",
    r"\bearly (?:access|users|adopters)\b",
    r"\b\d{2}% off\b|\bpromo code\b|\bdiscount code\b",
    r"\bfull write-?up\b|\blink (?:in|at) (?:the )?(?:comments|end|bio)\b",
    r"\bweekly update\b",
)]
LISTICLE_TITLE = re.compile(r"^\s*(?:top\s+)?\d+\s+[\w\s-]{0,40}?(?:tools|ways|tips|strategies|mistakes|reasons|lessons|things)\b", re.I)


def promo_signal(title: str, body: str) -> str:
    if m := LISTICLE_TITLE.search(title):
        return m.group(0).strip()
    for p in PROMO_PATTERNS:
        if m := p.search(f"{title}\n{body[:3000]}"):
            return m.group(0).strip()
    return ""


def backend() -> str:
    if settings.scorer != "auto":
        return settings.scorer
    return "jev" if settings.typesafe_api_key else "llm"


def score_thread(post: dict, replies: list[dict], product: dict, client: httpx.Client | None = None,
                 corrections: Sequence[dict] = ()) -> dict:
    http = client or httpx.Client(timeout=120)
    replies = [r for r in replies if r["author"] != post["author"]][:PROMPT_REPLIES]
    if backend() == "jev":
        answers, fit, reason, usage = _score_jev(post, replies, product, http)
    else:
        shots = fewshot.pick(post["title"], post["body"], corrections)
        answers, fit, reason, usage = _score_llm(post, replies, product, http, shots)
    promo = promo_signal(post["title"], post["body"])
    if promo:
        answers["is_vendor"] = True
    if not replies:
        answers["answered"] = False
    intent = intent_from_answers(answers)
    if intent in ("irrelevant", "showcase", "discussion"):
        answers["urgent"] = False
    if intent == "irrelevant":
        fit = 0.0
    if promo and intent == "showcase":
        reason = f'Self-promotion ("{promo}"). {reason}'.strip()
    return {
        "intent": intent,
        "intent_level": fit,
        "vendor_prob": 1.0 if intent == "showcase" else 0.0,
        "score": round(min(max(fit / (len(FIT_LEVELS) - 1), 0.0), 1.0) * 100),
        "reason": reason[:300],
        "urgent": _yes(answers.get("urgent")),
        "answered": _yes(answers.get("answered")),
        "usage": usage,
    }


def _yes(value) -> bool:
    return value is True or str(value).strip().lower() in ("true", "yes", "1")


def intent_from_answers(out: dict) -> str:
    if not _yes(out.get("on_topic")):
        return "irrelevant"
    if _yes(out.get("is_vendor")):
        return "showcase"
    if _yes(out.get("asks_for_tool")):
        return "buying"
    if _yes(out.get("has_problem")):
        return "pain"
    return "discussion"


def _replies_text(replies: list[dict]) -> str:
    if not replies:
        return "(no replies yet)"
    return "\n".join(f"- u/{r['author']}: {r['body'][:200]}" for r in replies)


def _examples_text(shots: list[dict]) -> str:
    return "\n\n".join(
        f"Product: {e['product']}\nTitle: {e['title']}\nText: {e['text']}\nTop replies: "
        f"{' | '.join(e['replies']) or '(none)'}\nAnswer: {json.dumps(e['answer'])}"
        for e in shots
    )


def _score_llm(post, replies, product, http, shots):
    prompt = LLM_PROMPT.format(
        product=json.dumps(product),
        subreddit=post["subreddit"],
        author=post["author"],
        num_comments=post.get("num_comments", len(replies)),
        title=post["title"],
        text=post["body"][:PROMPT_CHARS],
        replies=_replies_text(replies),
        questions="\n".join(f'"{k}": true/false. {q}' for k, q in QUESTIONS.items()),
        question_keys=", ".join(f'"{k}": <true/false>' for k in QUESTIONS),
        levels="\n".join(f"{i} = {d}" for i, d in enumerate(FIT_LEVELS)),
        examples=_examples_text(shots),
    )
    r = http.post(
        f"{settings.scorer_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.scorer_api_key}"},
        json={
            "model": settings.scorer_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            **({"reasoning_effort": settings.scorer_reasoning_effort} if settings.scorer_reasoning_effort else {}),
        },
    )
    r.raise_for_status()
    data = r.json()
    out = json.loads(data["choices"][0]["message"]["content"])
    usage = data.get("usage", {})
    return out, float(out.get("fit", 0)), str(out.get("reason", "")), {"input_tokens": usage.get("prompt_tokens", 0)}


def _score_jev(post, replies, product, http):
    payload = {
        "model": settings.jev_model,
        "state": {
            "product": product,
            "reddit_post": {
                "subreddit": post["subreddit"],
                "title": post["title"],
                "text": post["body"][:3000],
                "reply_count": post.get("num_comments", len(replies)),
                "top_replies": [r["body"][:300] for r in replies],
            },
        },
        "questions": {
            "fit": {
                "type": "score",
                "instructions": "How well does `product` fit the need of the original poster of `reddit_post`?",
                "criteria": FIT_LEVELS,
            },
            **{name: {"type": "noul", "instructions": f"About the original poster of `reddit_post`: {q}"} for name, q in QUESTIONS.items()},
        },
    }
    r = http.post(JEV_ENDPOINT, json=payload, headers={"Authorization": f"Bearer {settings.typesafe_api_key}"})
    r.raise_for_status()
    data = r.json()
    answers = data["answers"]
    lo, hi = _level_range(answers["fit"])
    fit = (float(answers["fit"]["score"]) - lo) / (hi - lo) * (len(FIT_LEVELS) - 1)
    out = {name: float(answers[name]["noul"]) >= 0.5 for name in QUESTIONS}
    return out, fit, "", data.get("usage", {})


def _level_range(answer: dict) -> tuple[float, float]:
    try:
        keys = [float(k) for k in answer.get("legend", {})]
        if len(keys) >= 2:
            return min(keys), max(keys)
    except ValueError:
        pass
    return 0.0, float(len(FIT_LEVELS) - 1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    p.add_argument("--product", default="A tool that finds potential customers on Reddit by monitoring keywords and scoring buying intent.")
    args = p.parse_args()
    post = {"subreddit": "test", "author": "someone", "title": args.text, "body": "", "num_comments": 0}
    print(f"scorer: {backend()}")
    print(json.dumps(score_thread(post, [], {"description": args.product}), indent=2))
