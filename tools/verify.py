#!/usr/bin/env python3
"""Offline self-check for this repo: no API key, no network, no cost.

    python3 tools/verify.py     # or: make verify

Checks the contract the README sells — the parsers handle both API shapes, the
batching helpers round-trip, the demo data has no unreachable answers, `--dry-run`
works without a key, the shipped assets are real, and no secret crept into git.
Exits non-zero on the first broken thing.
"""
import compileall
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "harness"
failures = []
count = 0


def ok(label, cond, detail=""):
    global count
    count += 1
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + str(detail)) if detail else ''}")
    if not cond:
        failures.append(label)


def main():
    print("1) every script compiles")
    for p in sorted(HARNESS.glob("*.py")) + [ROOT / "tools" / "verify.py", ROOT / "tools" / "build_poster.py"]:
        ok(f"compiles: {p.name}", compileall.compile_file(str(p), quiet=2, force=True) is True)

    print("2) typed answer parsing (both shapes the API has shipped)")
    sys.path.insert(0, str(HARNESS))
    import decision_client as dc
    ok("map shape", dc.probabilities({"probabilities": {"a": .7, "b": .3}}) == {"a": .7, "b": .3})
    ok("list shape", dc.probabilities({"choices": [{"option": "b", "probability": .6},
                                                   {"option": "a", "probability": .4}]}) == {"b": .6, "a": .4})
    ok("pick = argmax + prob", dc.pick({"probabilities": {"a": .2, "b": .8}}) == ("b", .8))
    ok("noul scalar", dc.scalar({"noul": .91}) == .91)
    ok("score scalar", dc.scalar({"score": 3}) == 3.0)

    print("3) batching round-trip (the 1-request-for-N-items trick)")
    keys = dc.batch_questions([{"id": "a"}, {"id": "b"}], "route", lambda it: {"type": "choice"})
    ok("keys are itNNN_<question>", list(keys) == ["it000_route", "it001_route"])
    ok("split_batch restores item order",
       dc.split_batch({"it000_route": 1, "it001_route": 2}, "route", 2) == [1, 2])

    print("4) demo data (a gold label outside the candidate list is an unwinnable item)")
    from demo_triage import QUEUES
    items = [json.loads(l) for l in (HARNESS / "data/tickets.jsonl").read_text().splitlines() if l.strip()]
    ok("tickets load", len(items) == 12, f"{len(items)}")
    ok("ids unique", len({i["id"] for i in items}) == len(items))
    unreachable = [i["id"] for i in items if i["gold_queue"] not in QUEUES]
    ok("no unreachable gold labels", not unreachable, unreachable)

    print("5) runs with no key (the README's first command)")
    r = subprocess.run([sys.executable, str(HARNESS / "demo_triage.py"), "--dry-run"],
                       capture_output=True, text=True, timeout=120)
    ok("--dry-run exits 0 without a key", r.returncode == 0,
       (r.stderr or "").strip().splitlines()[-1:] or "")
    ok("--dry-run shows the real payload", '"questions"' in r.stdout)
    r = subprocess.run([sys.executable, str(HARNESS / "decision_client.py"), "--selftest"],
                       capture_output=True, text=True, timeout=60)
    ok("decision_client --selftest", r.returncode == 0 and "passed" in r.stdout,
       r.stdout.strip().splitlines()[-1:])

    print("6) shipped assets are real, not placeholders")
    try:
        from PIL import Image
        gif = Image.open(ROOT / "assets" / "cheatsheet.gif")
        ok("cheat sheet gif animates", gif.n_frames > 1, f"{gif.n_frames} frames")
        ok("cheat sheet png is 1080x1350", Image.open(ROOT / "assets" / "cheatsheet.png").size == (1080, 1350))
    except ImportError:
        print("  SKIP  Pillow not installed — asset shape unchecked")

    print("7) the repo does not leak a key or an internal name")
    secret = re.compile(r"(TYPESAFE_API_KEY\s*=\s*[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{20,})")
    internal = re.compile(r"(invertio|sanad|0582104381)", re.I)
    hits = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or ".git/" in str(p) or p.name == "verify.py":
            continue
        if p.suffix not in {".md", ".py", ".json", ".jsonl", ".txt", ".yml", ".yaml", ".sh"}:
            continue
        text = p.read_text(errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if secret.search(line) or internal.search(line):
                hits.append(f"{p.relative_to(ROOT)}:{n}")
    ok("no key material, no internal names", not hits, hits[:4])

    print(f"\n{count - len(failures)}/{count} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
