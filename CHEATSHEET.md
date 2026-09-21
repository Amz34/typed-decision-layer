# Decision layer cheat sheet

*One page. Print it, pin it next to the router.*

---

## USE IT WHEN

- **A fork with a fixed label set** — route to one queue, one wave, one intent, one owner.
  If a human could answer with a single word, make it a typed decision.
- **Volume, or a worker lane** — cron sweeps, inbound floods, nightly re-scoring. Latency and
  round trips are the cost that compounds.
- **You need a number, not a sentence** — a probability you can threshold, escalate on, log,
  and later audit. `escalate` / `review` / `auto` needs a number to stand on.
- **Many little judgments about ONE item** — "which queue, is a human needed, is this abusive?"
  One request, several questions, one round trip.
- **Schema discipline matters** — a strict validator you cannot loosen, an interface you cannot
  repair after the fact.

## SKIP IT WHEN

- **Open-ended writing or explanation** — if the output is prose for a human, use a chat model.
- **One-off, human-in-the-loop calls** — a single interactive question does not need rails.
- **Your candidate list is the real problem** — if the right label is not in the list, no
  answerer can win. Fix retrieval first (we measured a **46.7%** ceiling on our own shortlist).
- **Irreversible actions on one un-thresholded probability** — add a gate, a review tier, or a
  second opinion. Never let p=0.34 delete something.

---

## THE THREE SHAPES

| how you send it | round trips | answer quality |
| --- | --- | --- |
| many **items** in one state, questions indexed by id | 1 | **collapses** — probabilities hedge to uniform |
| one **item** per call, its questions batched inside | 1 per item | **sharp** — this is the good shape |
| one item, one question, one call, one at a time | 1 per question | sharp but slow — fan the calls out instead |

- ✅ *"Batch the questions about one item."*
- ❌ *"Batch the items into one prompt."*

**Measured, 12 tickets, same model:** one-item-per-call, 8 concurrent → **1.53 s wall, 11/12 correct,
mean top-1 probability 0.99**. All 12 tickets in one state → 0.98 s, **3/12**, mean top-1 **0.33**.
Cheaper per token, worthless per decision.

## THE FOUR NUMBERS THAT MATTER

1. **hit rate** — is it right, and on how many items?
2. **ceiling** — how often was the right label even offered? (report it next to the hit rate)
3. **mean top-1 probability** — ≥ 0.9 is a decision; 0.33 is a coin flip in a suit
4. **latency and output tokens per decision** — what the lane costs when there are 10,000 of them

## THREE TRAPS

- **Mega-batching items** — see above. One round trip, useless answers.
- **Option order** — shuffling candidates flipped **30%** of picks. Pin the order and re-check.
- **Swapping the answerer without recalibrating** — same policy, different probability scale,
  different action mix (0 → 7 items moved from `review` to `act` for us). Recalibrate on labels.

## SHIP IT CHECKLIST

```
[ ] candidate labels written as label -> one-line description
[ ] question types: Choice for the fork, Noul/Score for the gates
[ ] one state per call, calls fanned out (not one prompt of many items)
[ ] thresholds chosen from measured probabilities, stored with the decision
[ ] ceiling + hit rate + mean top-1 probability written into the run log
[ ] the low-confidence tail goes to a human, not to production
```

---

Harness, demo and the full numbers: **github.com/Amz34/typed-decision-layer**
