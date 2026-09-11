PY := .venv/bin/python
STATE := state/catalog.json

.PHONY: help setup run watch test fixtures demo demo-terminal schedule-check clean

help:
	@echo "make run            two runs a day apart, so the change report has something in it"
	@echo "make watch          one run against fixtures/site-day2 (what cron calls)"
	@echo "make test           run the test suite"
	@echo "make schedule-check prove the cron wrapper works under cron's empty environment"
	@echo "make fixtures       regenerate the synthetic storefront"
	@echo "make demo           regenerate demo/out/demo.gif with Playwright, headless"
	@echo "make demo-terminal  the same story recorded with VHS instead"

setup:
	@./demo/setup.sh

# The headline. Run one is the baseline; run two is the morning after, and the
# only thing it reports is what moved.
run: setup
	@rm -f $(STATE)
	@echo "=== run 1 of 2: yesterday's catalogue (fixtures/site) ==="
	@$(PY) watch.py --serve fixtures/site --state $(STATE) --report
	@echo
	@echo "=== run 2 of 2: this morning's catalogue (fixtures/site-day2) ==="
	@$(PY) watch.py --serve fixtures/site-day2 --state $(STATE) --report
	@echo
	@echo "out/products.csv, out/products.xlsx and out/changes.txt are written."

watch: setup
	$(PY) watch.py --serve fixtures/site-day2 --state $(STATE) --report

test: setup
	$(PY) -m pytest -q

fixtures: setup
	$(PY) fixtures/generate_site.py

schedule-check:
	@./schedule/check.sh

demo:
	@./demo/record.sh

demo-terminal:
	@DEMO_RECIPE=vhs DEMO_OUT_DIR=demo/out-terminal ./demo/record.sh

clean:
	rm -rf out logs state demo/out demo/out-terminal demo/.toolchain demo/.scratch .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
