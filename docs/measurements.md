# What we measured, and what we could not reproduce

Everything here comes from our own box, our own traffic, our own money (the whole exercise cost
under a dollar in API spend). Where a number is a property of a *specific* purpose-built decision
model rather than of the pattern, we say so — the pattern is what you can copy today.

Reproduce any of it with `harness/bench.py` and `harness/demo_triage.py`.

---

## 1. Routing A/B — same items, same candidates, only the answerer changes

60 items with gold labels from a real routing corpus (our own agent traffic), identical candidate
lists in both arms, one arm per answerer.

| | typed decision lane | reasoning chat model | ratio |
| --- | --- | --- | --- |
| hit@1 | 26.7% (16/60) | 28.3% (17/60) | a wash |
| head-to-head | both right 12, only typed 4, only chat 4, neither 40 | | |
| mean latency | **0.75 s** | 17.15 s | **22.8× faster** |
| total output tokens | **14,711** | 258,330 | **17.6× fewer** |
| two-stage variant (gate + verify) | 1.66 s mean | — | — |

And the number that matters more than all of them:

> the gold label was inside the candidate shortlist only **46.7%** of the time.
> The ceiling was ~47%. Both answerers were fighting over half a problem.

That is why we print the ceiling next to the hit rate in `bench.py`. Blaming the decision layer for
a retrieval gap is the most expensive mistake in this whole area.

## 2. Production lane A/B — 77 decisions across 6 use cases

Same code, same specs, same fixtures, same policy thresholds; only the answerer changes.

| | typed decision lane | chat proxy | ratio |
| --- | --- | --- | --- |
| mean latency / decision | **733–763 ms** | 1,928–2,404 ms | ~2.7× faster |
| output tokens / decision | **138–207** | 250–455 | ~2× fewer |
| validator-clean full distributions | **77/77** | 0/77 | — |
| rows needing the lenient parser | **0** | 77/77 | — |
| intent triage where gold exists | **8/8** | 8/8 | a wash |

Same story as the routing A/B: the interface is the win. The strict validator never had to be
loosened for the typed lane, and never passed a single row of the chat lane.

## 3. Batching — the claim that survives, and the shape that does not

**Many questions, one item, one call** (13 typed judgments):
one call 8.96 s / 7,960 in / 2,596 out vs 13 sequential calls 24.69 s / 11,195 in / 2,633 out →
**2.76× faster, 1.41× fewer input tokens, 13:1 fewer round trips.**

**Many items, one call** (the trap, and the reason this repo has a `--mega-batch` flag):

| shape | requests | wall | in / out tokens | hit | mean top-1 prob |
| --- | --- | --- | --- | --- | --- |
| per item, 8 concurrent | 12 | 1.53 s | 6,029 / 949 | **11/12** | **0.99** |
| per item, sequential | 12 | 9.15 s | 6,029 / 949 | 11/12 | 0.99 |
| all 12 items in one state | **1** | 0.98 s | 3,224 / 1,012 | **3/12** | **0.33** |

Fewer input tokens, one round trip, and the distributions collapse toward uniform because the model
is hedging across unrelated items in one state. The single miss in the good shape was one item that
is genuinely ambiguous between "account" and "security" — a defensible human disagreement, not a
model failure.

## 4. Order sensitivity

Same 10 items, candidate order shuffled: **7/10 identical, 30% of picks flipped.** A typed decision
is not order-free. Pin the candidate order, or measure that the order does not matter for your
labels, before you build a threshold on top of it.

## 5. Where it does not help

**Guardrails, in our test.** 10 items with gold actions: typed lane 4/10, chat model 7/10. The typed
lane never emitted the permissive label at all (0/4 on the benign subset) and under-escalated one
genuine attack — it over-flagged. For a security gate over-flagging is the safe direction, but an
unreachable-by-construction label and one under-escalation mean we kept the existing answerer there.

The general lesson is not "decision layers are bad at safety". It is: **an answerer swap is a
policy change.** Thresholds fitted to one model's probability distribution produce a different
action mix on another model — same code, same policy, 0 → 7 items moved from `review` to `act`.
Recalibrate on labels before anything acts.

**Cheap local chat models.** A 3B model on CPU behind the same typed adapter returned a well-formed
typed answer — in 80 s, and 9/10 malformed on another run. The contract held; the answerer could
not. Typed decisions need a model that can make the decision, not just one that can fill the schema.

**Fast no-thinking chat mode.** Turning thinking off on a chat model gave 9× faster and 9× cheaper
calls — and accuracy collapsed to the embedding baseline (10.5% vs 28.3%). "Cheap and fast" is not
a substitute for an answerer trained to decide; that is the gap a purpose-built decision model fills.

## 6. Caveats we owe you

- Small n on several rows (12–77 items). Treat them as directional, and re-run on your own data —
  that is what the harness is for.
- One vendor, one model version at one point in time. We are not claiming a permanent property of
  anything; we are publishing a method and its output on one day.
- Latency depends on your cell, your region, and per-call overhead. Batching gains shrink when
  per-call overhead is small — our 2.76× measured against a vendor's "10×" claim is exactly that
  effect, and it is worth knowing before you promise a number to a client.
- Accuracy "a wash" means *on our items, with our candidate lists*. A different shortlist moves it.
