import argparse
import json
import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"

INTENTS = {
    "buying": "The author is actively looking for a tool, service, vendor, recommendation, or an alternative to a product they use, and this product could be the answer. Includes 'which X should I use', 'any recommendations for', 'looking for a tool that', 'switching away from <competitor>'.",
    "pain": "The author personally has a problem this product solves (frustration, struggle, workaround), but is not asking for a tool or recommendation.",
    "showcase": "The author is promoting, launching, or showing off their OWN product, service, or project in this space, or asking for feedback on something they built.",
    "discussion": "On-topic, but none of the above: news, opinions, tutorials, career questions, general chatter, or answering someone else.",
    "irrelevant": "Not about what this product does. The keywords matched by coincidence or mean something else here.",
}
FIT_LEVELS = [
    "This product would not help the author",
    "Loosely related; the product might help a little",
    "The product clearly addresses the author's situation",
    "The author is describing exactly what this product does",
]

QUESTIONS = {
    "on_topic": "Is this about the same problem space as the product, rather than a keyword that matched by coincidence?",
    "promotes_own": "Is the author sharing, launching, or asking for feedback on something THEY built or sell?",
    "asks_for_tool": "Is the author asking others to recommend, compare, or suggest a tool, service, product, or alternative?",
    "has_problem": "Does the author describe a problem of their own that the product would solve?",
}

LLM_PROMPT = """You check whether a Reddit post is a sales lead for a product.

Product: {product}

Reddit {kind} in r/{subreddit}:
Title: {title}
Text: {text}

Answer about the AUTHOR of this {kind}, based only on what they wrote.
"reason": one short sentence (max 20 words) on what the author wants.
{questions}
"fit": how well the product fits the author's need:
{levels}

Return only JSON: {{"reason": "<sentence>", {question_keys}, "fit": <0-3>}}"""


def backend() -> str:
    if settings.scorer != "auto":
        return settings.scorer
    return "jev" if settings.typesafe_api_key else "llm"


def score_item(item: dict, product: dict, client: httpx.Client | None = None) -> dict:
    http = client or httpx.Client(timeout=60)
    intent, fit, reason, usage = (_score_jev if backend() == "jev" else _score_llm)(item, product, http)
    if intent == "irrelevant":
        fit = 0.0
    return {
        "intent": intent,
        "intent_level": fit,
        "vendor_prob": 1.0 if intent == "showcase" else 0.0,
        "score": round(min(max(fit / (len(FIT_LEVELS) - 1), 0.0), 1.0) * 100),
        "reason": reason,
        "usage": usage,
    }


def _score_jev(item, product, http):
    payload = {
        "model": settings.jev_model,
        "state": {
            "product": product,
            "reddit_item": {
                "type": item["kind"],
                "subreddit": item["subreddit"],
                "title": item["title"],
                "text": item["body"][:3000],
            },
        },
        "questions": {
            "fit": {
                "type": "score",
                "instructions": "How well does `product` fit the need of the author of `reddit_item`?",
                "criteria": FIT_LEVELS,
            },
            **{
                name: {"type": "noul", "instructions": f"Does this describe the author of `reddit_item`? {INTENTS[name]}"}
                for name in ("buying", "pain", "showcase")
            },
        },
    }
    r = http.post(JEV_ENDPOINT, json=payload, headers={"Authorization": f"Bearer {settings.typesafe_api_key}"})
    r.raise_for_status()
    data = r.json()
    answers = data["answers"]
    fit_answer = answers["fit"]
    lo, hi = _level_range(fit_answer)
    fit = (float(fit_answer["score"]) - lo) / (hi - lo) * (len(FIT_LEVELS) - 1)
    probs = {name: float(answers[name]["noul"]) for name in ("buying", "pain", "showcase")}
    best = max(probs, key=probs.get)
    intent = best if probs[best] >= 0.5 else ("discussion" if fit >= 1 else "irrelevant")
    return intent, fit, "", data.get("usage", {})


def _level_range(answer: dict) -> tuple[float, float]:
    try:
        keys = [float(k) for k in answer.get("legend", {})]
        if len(keys) >= 2:
            return min(keys), max(keys)
    except ValueError:
        pass
    return 0.0, float(len(FIT_LEVELS) - 1)


def _yes(value) -> bool:
    return value is True or str(value).strip().lower() in ("true", "yes", "1")


def intent_from_answers(out: dict) -> str:
    if not _yes(out.get("on_topic")):
        return "irrelevant"
    if _yes(out.get("promotes_own")):
        return "showcase"
    if _yes(out.get("asks_for_tool")):
        return "buying"
    if _yes(out.get("has_problem")):
        return "pain"
    return "discussion"


def _score_llm(item, product, http):
    prompt = LLM_PROMPT.format(
        product=json.dumps(product),
        kind=item["kind"],
        subreddit=item["subreddit"],
        title=item["title"],
        text=item["body"][:3000],
        questions="\n".join(f'"{k}": true/false. {q}' for k, q in QUESTIONS.items()),
        question_keys=", ".join(f'"{k}": <true/false>' for k in QUESTIONS),
        levels="\n".join(f"{i} = {d}" for i, d in enumerate(FIT_LEVELS)),
    )
    r = http.post(
        f"{settings.scorer_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.scorer_api_key}"},
        json={
            "model": settings.scorer_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        },
    )
    r.raise_for_status()
    data = r.json()
    out = json.loads(data["choices"][0]["message"]["content"])
    usage = data.get("usage", {})
    return intent_from_answers(out), float(out.get("fit", 0)), str(out.get("reason", ""))[:300], {"input_tokens": usage.get("prompt_tokens", 0)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    p.add_argument("--product", default="A tool that finds potential customers on Reddit by monitoring keywords and scoring buying intent.")
    args = p.parse_args()
    item = {"kind": "post", "subreddit": "test", "title": args.text, "body": ""}
    print(f"scorer: {backend()}")
    print(json.dumps(score_item(item, {"description": args.product}), indent=2))
