import argparse
import json
import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"

INTENT_LEVELS = [
    "Unrelated to the product's problem space",
    "Discusses the topic but shows no problem or need of their own",
    "Describes a problem the product solves, but is not looking for a solution",
    "Actively asking for a tool, service, recommendation or help that the product provides",
]

LLM_PROMPT = """You qualify Reddit leads for a product.

Product: {product}

Reddit {kind} in r/{subreddit}:
Title: {title}
Text: {text}

Rate the author's buying intent for this product:
{levels}

Return only JSON: {{"intent": <0-3>, "vendor": <true if the author is promoting their own product or service, else false>}}"""


def backend() -> str:
    if settings.scorer != "auto":
        return settings.scorer
    return "jev" if settings.typesafe_api_key else "llm"


def score_item(item: dict, product: dict, client: httpx.Client | None = None) -> dict:
    http = client or httpx.Client(timeout=60)
    level, lo, hi, vendor, usage = (_score_jev if backend() == "jev" else _score_llm)(item, product, http)
    intent_norm = min(max((level - lo) / (hi - lo), 0.0), 1.0)
    return {
        "intent_level": level,
        "vendor_prob": vendor,
        "score": round(intent_norm * 100 * (1 - vendor)),
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
            "intent": {
                "type": "score",
                "instructions": "How strong is the buying intent of the author of `reddit_item` for what `product` offers?",
                "criteria": INTENT_LEVELS,
            },
            "vendor": {
                "type": "noul",
                "instructions": "Is the author of `reddit_item` promoting their own product or service, rather than looking for one?",
            },
        },
    }
    r = http.post(JEV_ENDPOINT, json=payload, headers={"Authorization": f"Bearer {settings.typesafe_api_key}"})
    r.raise_for_status()
    data = r.json()
    intent = data["answers"]["intent"]
    lo, hi = _level_range(intent)
    return float(intent["score"]), lo, hi, float(data["answers"]["vendor"]["noul"]), data.get("usage", {})


def _level_range(answer: dict) -> tuple[float, float]:
    try:
        keys = [float(k) for k in answer.get("legend", {})]
        if len(keys) >= 2:
            return min(keys), max(keys)
    except ValueError:
        pass
    return 0.0, float(len(INTENT_LEVELS) - 1)


def _score_llm(item, product, http):
    prompt = LLM_PROMPT.format(
        product=json.dumps(product),
        kind=item["kind"],
        subreddit=item["subreddit"],
        title=item["title"],
        text=item["body"][:3000],
        levels="\n".join(f"{i} = {d}" for i, d in enumerate(INTENT_LEVELS)),
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
    vendor = out.get("vendor", False)
    vendor = float(vendor) if not isinstance(vendor, str) else float(vendor.lower() == "true")
    usage = data.get("usage", {})
    return float(out["intent"]), 0.0, float(len(INTENT_LEVELS) - 1), vendor, {"input_tokens": usage.get("prompt_tokens", 0)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    p.add_argument("--product", default="A tool that finds potential customers on Reddit by monitoring keywords and scoring buying intent.")
    args = p.parse_args()
    item = {"kind": "post", "subreddit": "test", "title": args.text, "body": ""}
    print(f"scorer: {backend()}")
    print(json.dumps(score_item(item, {"description": args.product}), indent=2))
