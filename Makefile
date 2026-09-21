# Typed decision layer — harness
PY ?= python3

.PHONY: help verify selftest dry demo bench poster clean
help:
	@echo "make verify     # offline self-check: parsers, batching, data, assets, no leaks"
	@echo "make selftest   # unit checks, no API key needed"
	@echo "make dry        # print the exact request payload for one ticket"
	@echo "make demo       # 12 tickets, 2 typed judgments each, one call per ticket (needs TYPESAFE_API_KEY)"
	@echo "make bench      # same items, both lanes: typed decision vs chat model"
	@echo "make poster     # rebuild assets/cheatsheet.{png,gif}"
	@echo ""
	@echo "Never put a key in a file: export TYPESAFE_API_KEY=... (or use a secret manager)"

selftest:
	$(PY) harness/decision_client.py --selftest

verify:
	$(PY) tools/verify.py

dry:
	cd harness && $(PY) demo_triage.py --dry-run

demo:
	cd harness && $(PY) demo_triage.py --per-item --workers 8

bench:
	cd harness && $(PY) bench.py --lane decision --out out/bench_decision.json
	cd harness && $(PY) bench.py --lane chat --out out/bench_chat.json
	$(PY) -c "import json;[print(json.load(open('harness/out/bench_'+l+'.json'))) for l in ('decision','chat')]"

poster:
	$(PY) tools/build_poster.py

clean:
	rm -rf harness/out/*.json tools/frames/*.png html/*.html
