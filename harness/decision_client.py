#!/usr/bin/env python3
"""Typed decision layer client — one function that returns NUMBERS instead of prose.

The whole idea in one sentence: instead of asking a chat model "which queue should
this ticket go to?" and parsing the sentence it writes back, you ask a decision
model a *typed* question and get a probability distribution. Probabilities you can
threshold, log, escalate on, and batch.

Three primitives:

    Choice  -> pick one label out of a candidate list, with probabilities
    Score   -> put a number on an item (e.g. how urgent is this, 0-1)
    Noul    -> a yes/no judgment with a probability ("is this person a real buyer?")

They can all be asked in ONE request, about MANY items: that is the part that
changes the shape of a worker lane. 13 typed questions cost one round trip.

This file is stdlib-only on purpose: drop it in anywhere.

    export TYPESAFE_API_KEY=...        # any typed-decision endpoint
    python3 decision_client.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("DECISION_API_URL", "https://api.typesafe.ai/v1/systemone")
DEFAULT_MODEL = os.environ.get("DECISION_MODEL", "jev-latest")
API_KEY_ENV = os.environ.get("DECISION_API_KEY_ENV", "TYPESAFE_API_KEY")


class DecisionError(Exception):
    """Raised for transport and payload problems (never for a low probability)."""


def key_info() -> tuple[bool, str]:
    """(key present?, short fingerprint) — never returns the key itself."""
    key = os.environ.get(API_KEY_ENV, "")
    if not key:
        return False, ""
    return True, hashlib.sha256(key.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# one request, many questions
# --------------------------------------------------------------------------- #
def ask(
    state: str,
    questions: dict,
    model: str = DEFAULT_MODEL,
    url: str = DEFAULT_URL,
    timeout: int = 180,
    retries: int = 2,
) -> tuple[dict, dict, float, int]:
    """One typed request.

    `state` is the thing being judged (a ticket, a lead, a document — anything).
    `questions` is a name -> spec map, where spec is
        {"type": "choice", "instructions": "...", "criteria": {"label": "description"}}
        {"type": "noul",   "instructions": "..."}
        {"type": "score",  "instructions": "..."}

    Returns (answers, usage, latency_seconds, attempts).
    """
    ok, _fp = key_info()
    if not ok:
        raise DecisionError(f"{API_KEY_ENV} is not set")

    body = {"state": state, "model": model, "questions": questions}
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + os.environ[API_KEY_ENV],
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            return data["answers"], data.get("usage", {}), time.time() - started, attempt + 1
        except urllib.error.HTTPError as exc:            # noqa: PERF203
            detail = exc.read().decode()[:300]
            last = DecisionError(f"HTTP {exc.code}: {detail}")
            if exc.code in (400, 401, 403, 422):         # retrying cannot help
                break
        except Exception as exc:                         # noqa: BLE001 - timeouts, resets, bad json
            last = DecisionError(f"{type(exc).__name__}: {str(exc)[:200]}")
        time.sleep(1.5 * (attempt + 1))
    raise last if last else DecisionError("unknown failure")


# --------------------------------------------------------------------------- #
# reading the typed answers
# --------------------------------------------------------------------------- #
def probabilities(answer) -> dict:
    """Normalise a Choice answer into {label: probability}.

    The API has shipped both shapes (a map, and a list of objects) at different
    times, so parse defensively — never trust one shape in production.
    """
    if isinstance(answer, dict):
        raw = answer.get("probabilities") or answer.get("choices")
        if isinstance(raw, dict):
            return {str(k): float(v) for k, v in raw.items()}
        if isinstance(raw, list):
            out = {}
            for item in raw:
                if isinstance(item, dict):
                    label = item.get("option") or item.get("choice") or item.get("name")
                    if label is not None:
                        out[str(label)] = float(
                            item.get("probability", item.get("prob", 0.0))
                        )
            return out
    raise DecisionError(f"unrecognised Choice payload: {str(answer)[:200]}")


def scalar(answer) -> float:
    """Normalise a Noul / Score answer into a single float."""
    if isinstance(answer, dict):
        for field in ("noul", "score", "probability", "prob", "value"):
            value = answer.get(field)
            if isinstance(value, (int, float)):
                return float(value)
    raise DecisionError(f"unrecognised Noul/Score payload: {str(answer)[:200]}")


def pick(answer) -> tuple[str | None, float]:
    """Highest-probability label and its probability."""
    probs = probabilities(answer)
    if not probs:
        return None, 0.0
    label = max(probs, key=probs.get)
    return label, probs[label]


# --------------------------------------------------------------------------- #
# batching: many items, one round trip
# --------------------------------------------------------------------------- #
def batch_questions(items, question_name: str, spec_for) -> dict:
    """Flatten N items x 1 question into one question map.

    `spec_for(item)` returns a question spec; the returned keys are
    `it000_<question_name>`, `it001_<question_name>`, ... so a caller can put the
    answers straight back onto the items. This is the whole batching trick: the
    model answers 20 tickets in one request instead of 20.
    """
    questions = {}
    for idx, item in enumerate(items):
        questions[f"it{idx:03d}_{question_name}"] = spec_for(item)
    return questions


def split_batch(answers: dict, answer_name: str, n_items: int) -> list:
    """Inverse of batch_questions(): pull answers back out in item order."""
    out = []
    for idx in range(n_items):
        out.append(answers.get(f"it{idx:03d}_{answer_name}"))
    return out


def selftest() -> int:
    """Offline check of parsing + batching, no API key, no network."""
    checks = []

    def check(name, got, want):
        ok = got == want
        checks.append(ok)
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {got!r}")

    print("decision_client selftest")
    check("map shape", probabilities({"probabilities": {"a": 0.7, "b": 0.3}}), {"a": 0.7, "b": 0.3})
    check(
        "list shape",
        probabilities({"choices": [{"option": "a", "probability": 0.6}, {"option": "b", "probability": 0.4}]}),
        {"a": 0.6, "b": 0.4},
    )
    check("pick", pick({"probabilities": {"a": 0.2, "b": 0.8}}), ("b", 0.8))
    check("noul", scalar({"noul": 0.91}), 0.91)
    check("score", scalar({"score": 3}), 3.0)

    items = ["one", "two", "three"]
    qs = batch_questions(items, "route", lambda it: {"type": "choice", "instructions": it})
    check("batch keys", sorted(qs), ["it000_route", "it001_route", "it002_route"])
    answers = {f"it{i:03d}_route": {"probabilities": {"x": 1.0}} for i in range(3)}
    check("batch round-trip", split_batch(answers, "route", 3)[1], {"probabilities": {"x": 1.0}})

    print(f"{sum(checks)}/{len(checks)} passed")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="typed decision layer client")
    ap.add_argument("--selftest", action="store_true", help="offline checks, no key needed")
    args = ap.parse_args()
    if args.selftest:
        raise SystemExit(selftest())
    ok, fp = key_info()
    print(f"key present: {ok}  fingerprint: {fp or '-'}  endpoint: {DEFAULT_URL}")
