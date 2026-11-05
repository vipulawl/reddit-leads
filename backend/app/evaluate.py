import argparse
import time

import httpx

from .config import settings
from .reddit import make_reddit
from .scorer import promo_signal, score_thread

LEAD = {"buying", "pain"}
NOT_LEAD = {"showcase", "discussion", "irrelevant"}

# Real r/aeo, r/SEO, r/shopify... threads (fetched live, only ids stored here), hand-labelled for the product below.
EXPECTED = {
    "1x5n7lb": {"buying"},
    "1x5sa0x": NOT_LEAD,
    "1xfolg2": {"buying"},
    "1xfomox": {"buying"},
    "1xibnyi": {"buying"},
    "1xjp5hz": {"buying"},
    "1xk0yle": {"showcase"},
    "1xk36a4": LEAD,
    "1xk4286": NOT_LEAD,
    "1xkok8k": NOT_LEAD,
    "1xkyu0d": {"irrelevant", "discussion"},
    "1xl6j16": NOT_LEAD,
    "1xlupzn": {"showcase"},
    "1xlwa23": {"showcase"},
    "1xlx3sc": NOT_LEAD,
    "1xlxd5a": {"showcase"},
    "1xmn82t": {"showcase"},
    "1xmn887": {"showcase"},
}

PRODUCT = {
    "name": "SellOnLLM",
    "description": "A free AI visibility checker that shows businesses whether AI assistants cite their brand or "
                   "competitors when answering buyer questions, with competitor monitoring.",
    "ideal_customer": "Founders and marketing teams at eCommerce and SaaS companies who want to improve their AI "
                      "visibility and track competitors.",
    "problems_solved": [
        "not knowing if AI assistants recommend my brand",
        "competitors get more visibility in AI answers",
        "no quick way to check AI visibility without signing up",
        "don't know how to make my site AI-ready",
    ],
    "competitors": ["Otterly", "Peec AI", "Profound"],
}


def main():
    p = argparse.ArgumentParser(description="Score 18 hand-labelled Reddit threads with the configured SCORER_* model")
    p.add_argument("--model", help="override SCORER_MODEL")
    p.add_argument("--base-url", help="override SCORER_BASE_URL")
    p.add_argument("--reasoning-effort", help="override SCORER_REASONING_EFFORT, e.g. none for qwen3")
    p.add_argument("--onboarding-provider", action="store_true", help="use LLM_BASE_URL and LLM_API_KEY instead of SCORER_*")
    p.add_argument("--limit", type=int, help="score only the first N threads")
    args = p.parse_args()
    settings.scorer = "llm"
    if args.onboarding_provider:
        settings.scorer_base_url, settings.scorer_api_key = settings.llm_base_url, settings.llm_api_key
    settings.scorer_model = args.model or settings.scorer_model
    settings.scorer_base_url = args.base_url or settings.scorer_base_url
    settings.scorer_reasoning_effort = args.reasoning_effort or settings.scorer_reasoning_effort

    reddit, http = make_reddit(), httpx.Client(timeout=180)
    ok = total = lead_ok = lead_total = leaked = skipped = 0
    start = time.time()
    for pid, want in list(EXPECTED.items())[: args.limit]:
        post, replies = reddit.thread(f"t3_{pid}")
        if post["removed"]:
            skipped += 1
            print(f"--- removed on Reddit, skipped | {pid}")
            continue
        res = score_thread(post, replies, PRODUCT, http)
        good = res["intent"] in want
        total += 1
        ok += good
        if want <= LEAD:
            lead_total += 1
            lead_ok += res["intent"] in LEAD
        if want <= NOT_LEAD and res["intent"] in LEAD:
            leaked += 1
        promo = promo_signal(post["title"], post["body"])[:25]
        print(f"{'OK ' if good else 'BAD'} {res['intent']:10} fit={res['score']:3} promo={promo!r:28} | {post['title'][:60]}")
    print(f"\n{settings.scorer_model}: {ok}/{total} correct, real leads kept {lead_ok}/{lead_total}, "
          f"non-leads shown as leads {leaked}, {skipped} removed threads skipped, "
          f"{(time.time() - start) / max(total, 1):.1f}s per thread")


if __name__ == "__main__":
    main()
