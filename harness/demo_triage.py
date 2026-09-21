#!/usr/bin/env python3
"""Triage demo: 12 support tickets, typed route + escalate judgment each.

The point is not that a decision model is clever. The point is that the answer
comes back as NUMBERS — a probability per queue and a probability that a human is
needed — so the routing becomes a threshold instead of a prompt you hope behaves.

Three shapes, same 12 tickets. The middle one is the trap.

    python3 demo_triage.py --dry-run                  # print the payload, no key needed
    python3 demo_triage.py --per-item --workers 8      # RECOMMENDED: 1 call per ticket
    python3 demo_triage.py --one-at-a-time             # same calls, no concurrency
    python3 demo_triage.py --mega-batch                # ANTI-PATTERN: all 12 in one state

Measured on our box (12 tickets, jev-latest, 6 queues):

    mega-batch   1 call   0.98 s   3,224 in / 1,012 out   route hit  3/12   probs ~0.33 (hedged)
    one-at-a-time 12 calls 9.15 s   6,029 in /   949 out   route hit 11/12   probs 0.89-1.00
    per-item @8  12 calls ~1.3 s    6,029 in /   949 out   route hit 11/12   probs 0.89-1.00

Read it carefully: batching MANY ITEMS into one state makes the distributions
collapse toward uniform — the model hedges across a page of unrelated tickets.
Batching the QUESTIONS about ONE item is free and keeps the distribution sharp.
So: one state per call, fan the calls out, keep one round trip per item.

Requires the key in the env (DECISION_API_KEY_ENV, default TYPESAFE_API_KEY).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decision_client import (  # noqa: E402
    DecisionError,
    ask,
    batch_questions,
    key_info,
    pick,
    scalar,
    split_batch,
)

HERE = os.path.dirname(os.path.abspath(__file__))

QUEUES = {
    "billing": "Money: invoices, charges, refunds, payment plans, tax documents",
    "technical": "The product is broken, slow, or losing data or events",
    "account": "People, access, seats, login, workspace settings",
    "security": "Fraud, impersonation, credentials, suspicious or abusive activity",
    "feature_request": "A capability that does not exist yet, or a change request",
    "other": "Praise, feedback, or nothing that needs a queue at all",
}

QUESTIONS = {
    "route": {
        "type": "choice",
        "instructions": "Which single queue should own this ticket? Put most probability on the best one.",
        "criteria": QUEUES,
    },
    "needs_human": {
        "type": "noul",
        "instructions": "Does this ticket need a human to reply personally, rather than being handled "
        "by a self-serve answer, a refund macro, or a scheduled job?",
    },
}

# thresholded action — the thing that makes this a decision layer, not a suggestion


def verdict(route: str | None, route_prob: float, needs_human: float) -> str:
    if needs_human >= 0.70:
        return "escalate"
    if route == "security" and needs_human >= 0.40:
        return "escalate"
    if route_prob < 0.45:
        return "review"
    return "auto"


def load_items(path: str) -> list[dict]:
    items = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                items.append(json.loads(line))
    return items


def row_from_answers(item: dict, answers: dict) -> dict:
    route, prob = pick(answers["route"])
    human = scalar(answers["needs_human"])
    return {
        "id": item["id"],
        "route": route,
        "route_prob": round(prob, 3),
        "needs_human": round(human, 3),
        "action": verdict(route, prob, human),
        "gold_queue": item.get("gold_queue"),
    }


def run_per_item(items: list[dict], workers: int) -> tuple[list[dict], dict]:
    """One request per item; concurrency fans the round trips out."""
    started = time.time()

    def one(item: dict) -> tuple[dict, dict]:
        answers, usage, _latency, _attempts = ask("Ticket:\n" + item["text"], QUESTIONS)
        return row_from_answers(item, answers), usage

    results = [None] * len(items)
    in_tok = out_tok = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for idx, (row, usage) in zip(range(len(items)), pool.map(one, items)):
            results[idx] = row
            in_tok += usage.get("input_tokens", 0)
            out_tok += usage.get("output_tokens", 0)
    wall = time.time() - started
    return results, {
        "mode": f"per-item x{workers}",
        "requests": len(items),
        "wall": wall,
        "in_tok": in_tok,
        "out_tok": out_tok,
    }


def run_mega_batch(items: list[dict]) -> tuple[list[dict], dict]:
    """ANTI-PATTERN: every ticket inside one state, all questions in one request."""
    questions = batch_questions(items, "route", lambda _it: QUESTIONS["route"])
    questions |= batch_questions(items, "needs_human", lambda _it: QUESTIONS["needs_human"])
    state = "Tickets, numbered in the question keys:\n" + "\n".join(
        f"[{idx:03d}] {item['text']}" for idx, item in enumerate(items)
    )
    started = time.time()
    answers, usage, _latency, _attempts = ask(state, questions)
    wall = time.time() - started
    routes = split_batch(answers, "route", len(items))
    humans = split_batch(answers, "needs_human", len(items))
    rows = []
    for idx, item in enumerate(items):
        rows.append(row_from_answers(item, {"route": routes[idx], "needs_human": humans[idx]}))
    return rows, {
        "mode": "mega-batch",
        "requests": 1,
        "wall": wall,
        "in_tok": usage.get("input_tokens", 0),
        "out_tok": usage.get("output_tokens", 0),
    }


def report(rows: list[dict], meta: dict) -> None:
    scored = [r for r in rows if r["gold_queue"]]
    hit = sum(1 for r in scored if r["route"] == r["gold_queue"])
    probs = [r["route_prob"] for r in scored]
    print(f"\n{'id':<7}{'route':<17}{'p':>6}{'human':>7}{'action':>10}  gold")
    print("-" * 62)
    for row in rows:
        miss = "  <- miss" if row["gold_queue"] and row["route"] != row["gold_queue"] else ""
        print(
            f"{row['id']:<7}{str(row['route']):<17}{row['route_prob']:>6.2f}"
            f"{row['needs_human']:>7.2f}{row['action']:>10}  {row['gold_queue'] or '-'}{miss}"
        )
    actions = {}
    for row in rows:
        actions[row["action"]] = actions.get(row["action"], 0) + 1
    print("-" * 62)
    print(
        f"{meta['mode']:<16} requests {meta['requests']:<3} wall {meta['wall']:>5.2f}s   "
        f"in {meta['in_tok']:>5} / out {meta['out_tok']:>4} tok   "
        f"route hit {hit}/{len(scored)}   mean top-1 prob {sum(probs) / len(probs):.2f}"
    )
    print(f"actions {actions}")


def dry_run(items: list[dict]) -> int:
    payload = {
        "state": "Ticket:\n" + items[0]["text"],
        "model": os.environ.get("DECISION_MODEL", "jev-latest"),
        "questions": QUESTIONS,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nthat is ONE request for ONE ticket ({len(QUESTIONS)} typed questions).")
    print("export TYPESAFE_API_KEY=... to run it live (see --per-item).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", default=os.path.join(HERE, "data", "tickets.jsonl"))
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--per-item", action="store_true", help="one request per item, concurrent (recommended)")
    group.add_argument("--one-at-a-time", action="store_true", help="one request per item, sequential")
    group.add_argument("--mega-batch", action="store_true", help="all items in one state (anti-pattern)")
    ap.add_argument("--workers", type=int, default=8, help="concurrency for --per-item")
    ap.add_argument("--dry-run", action="store_true", help="print the request and exit, no key needed")
    ap.add_argument("--out", default=os.path.join(HERE, "out", "triage_run.json"))
    args = ap.parse_args()

    items = load_items(args.items)
    if args.dry_run:
        return dry_run(items)

    ok, fingerprint = key_info()
    if not ok:
        print("no key in env — use --dry-run, or export TYPESAFE_API_KEY=...")
        return 2
    print(f"key {fingerprint} · {len(items)} tickets · starting")
    try:
        if args.mega_batch:
            rows, meta = run_mega_batch(items)
        else:
            workers = 1 if args.one_at_a_time else args.workers
            rows, meta = run_per_item(items, workers)
    except DecisionError as exc:
        print(f"decision call failed: {exc}")
        return 1
    report(rows, meta)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump({"meta": meta, "rows": rows}, handle, indent=2, ensure_ascii=False)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
