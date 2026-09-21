#!/usr/bin/env python3
"""Bench: the SAME items, two answerers, only the decision layer changes.

Lane A  decision  -> typed Choice/Score/Noul, answers come back as probabilities
Lane B  chat      -> any OpenAI-compatible endpoint, asked for the same labels

Both arms see the identical candidate list, so the only thing being compared is
the decision interface. What we report, deliberately:

    hit rate          did the answer match the gold label
    ceiling           was the gold label even in the candidate list (a retriever
                      that never offers the right queue caps every answerer)
    mean top-1 prob   how confident the distribution was (hedging detector)
    latency / tokens  what the interface costs per decision

Run:

    export TYPESAFE_API_KEY=...
    export CHAT_BASE_URL=https://api.deepseek.com/v1 CHAT_API_KEY=... CHAT_MODEL=deepseek-chat

    python3 bench.py --lane decision --items data/tickets.jsonl
    python3 bench.py --lane chat     --items data/tickets.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decision_client import DecisionError, ask, pick  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def load_items(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# --------------------------------------------------------------------------- #
# lane A: typed decision
# --------------------------------------------------------------------------- #
def decision_answer(text: str, labels: dict) -> tuple[str | None, float, float, dict]:
    questions = {
        "route": {
            "type": "choice",
            "instructions": "Which single queue should own this ticket? Put most probability on the best one.",
            "criteria": labels,
        }
    }
    answers, usage, latency, _attempts = ask("Ticket:\n" + text, questions)
    label, prob = pick(answers["route"])
    return label, prob, latency, usage


# --------------------------------------------------------------------------- #
# lane B: chat model asked for the same label
# --------------------------------------------------------------------------- #
CHAT_PROMPT = (
    "You route support tickets. Choose exactly one queue for the ticket below and answer "
    'with a JSON object only, like {{"route": "<queue>"}}.\n\nQueues:\n{choices}\n\nTicket:\n{text}'
)


def chat_answer(text: str, labels: dict) -> tuple[str | None, float, float, dict]:
    base = os.environ.get("CHAT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("CHAT_MODEL", "gpt-4o-mini")
    key = os.environ.get("CHAT_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise DecisionError("CHAT_API_KEY not set")
    choices = "\n".join(f"- {name}: {desc}" for name, desc in labels.items())
    body = {
        "model": model,
        "messages": [{"role": "user", "content": CHAT_PROMPT.format(choices=choices, text=text)}],
        "temperature": 0,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    latency = time.time() - started
    content = data["choices"][0]["message"]["content"]
    usage = {
        "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
        "output_tokens": data.get("usage", {}).get("completion_tokens", 0),
    }
    raw = content.strip()
    fenced = re.search(r"\{.*\}", raw, re.S)          # models love ```json fences
    label = None
    try:
        parsed = json.loads(fenced.group(0) if fenced else raw)
        candidate = parsed.get("route") if isinstance(parsed, dict) else parsed
        if isinstance(candidate, str):
            for name in labels:                        # case / whitespace tolerant
                if candidate.strip().lower() == name.lower():
                    label = name
                    break
    except (json.JSONDecodeError, AttributeError):
        label = None
    return label, 0.0, latency, usage


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lane", choices=["decision", "chat"], required=True)
    ap.add_argument("--items", default=os.path.join(HERE, "data", "tickets.jsonl"))
    ap.add_argument("--limit", type=int, default=0, help="only first N items")
    ap.add_argument("--candidates", default="", help="JSON file: {label: description}; default = the 6 demo queues")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    labels = {
        "billing": "Money: invoices, charges, refunds, payment plans, tax documents",
        "technical": "The product is broken, slow, or losing data or events",
        "account": "People, access, seats, login, workspace settings",
        "security": "Fraud, impersonation, credentials, suspicious or abusive activity",
        "feature_request": "A capability that does not exist yet, or a change request",
        "other": "Praise, feedback, or nothing that needs a queue at all",
    }
    if args.candidates:
        with open(args.candidates, encoding="utf-8") as handle:
            labels = json.load(handle)

    items = load_items(args.items)
    if args.limit:
        items = items[: args.limit]
    answer = decision_answer if args.lane == "decision" else chat_answer

    rows, latencies, out_tokens, probs = [], [], [], []
    for item in items:
        try:
            label, prob, latency, usage = answer(item["text"], labels)
        except (DecisionError, urllib.error.URLError) as exc:
            label, prob, latency, usage = None, 0.0, 0.0, {}
            print(f"  {item['id']}: call failed ({exc})")
        latencies.append(latency)
        out_tokens.append(usage.get("output_tokens", 0))
        probs.append(prob)
        rows.append(
            {
                "id": item["id"],
                "predicted": label,
                "gold": item.get("gold_queue"),
                "hit": bool(label and label == item.get("gold_queue")),
                "top1_prob": round(prob, 3),
                "latency": round(latency, 3),
                "out_tokens": usage.get("output_tokens", 0),
            }
        )
        print(f"  {item['id']:<7}{str(label):<17}gold {str(item.get('gold_queue')):<17}"
              f"{'hit' if rows[-1]['hit'] else 'miss':<5}p={rows[-1]['top1_prob']:.2f} "
              f"{latency:.2f}s")

    scored = [r for r in rows if r["gold"]]
    hits = sum(1 for r in scored if r["hit"])
    ceiling = sum(1 for r in scored if r["gold"] in labels)
    hedged = sum(1 for r in scored if r["top1_prob"] < 0.50)
    summary = {
        "lane": args.lane,
        "n": len(scored),
        "hits": hits,
        "hit_pct": round(100 * hits / len(scored), 1) if scored else 0.0,
        "ceiling_pct": round(100 * ceiling / len(scored), 1) if scored else 0.0,
        "hedged_below_0.50": hedged,
        "mean_latency_s": round(statistics.mean(latencies), 3) if latencies else 0.0,
        "mean_out_tokens": round(statistics.mean(out_tokens), 1) if out_tokens else 0.0,
        "parse_failures": sum(1 for r in rows if r["predicted"] is None),
    }
    print("\n" + json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"summary": summary, "rows": rows}, handle, indent=2)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
