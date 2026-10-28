import argparse
import json
import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)
ENDPOINT = "https://api.typesafe.ai/v1/systemone"

INTENT_LEVELS = [
    "Unrelated to the product's problem space",
    "Discusses the topic but shows no problem or need of their own",
    "Describes a problem the product solves, but is not looking for a solution",
    "Actively asking for a tool, service, recommendation or help that the product provides",
]


def score_item(item: dict, product: dict, client: httpx.Client | None = None) -> dict:
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
    http = client or httpx.Client(timeout=20)
    r = http.post(ENDPOINT, json=payload, headers={"Authorization": f"Bearer {settings.typesafe_api_key}"})
    r.raise_for_status()
    data = r.json()
    intent = data["answers"]["intent"]
    vendor = float(data["answers"]["vendor"]["noul"])
    level = float(intent["score"])
    lo, hi = _level_range(intent)
    intent_norm = min(max((level - lo) / (hi - lo), 0.0), 1.0)
    return {
        "intent_level": level,
        "vendor_prob": vendor,
        "score": round(intent_norm * 100 * (1 - vendor)),
        "usage": data.get("usage", {}),
    }


def _level_range(answer: dict) -> tuple[float, float]:
    try:
        keys = [float(k) for k in answer.get("legend", {})]
        if len(keys) >= 2:
            return min(keys), max(keys)
    except ValueError:
        pass
    return 0.0, float(len(INTENT_LEVELS) - 1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    p.add_argument("--product", default="A tool that finds potential customers on Reddit by monitoring keywords and scoring buying intent.")
    args = p.parse_args()
    item = {"kind": "post", "subreddit": "test", "title": args.text, "body": ""}
    print(json.dumps(score_item(item, {"description": args.product}), indent=2))
