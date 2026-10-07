# Thin wrapper over tasks.py so make and Windows (`py tasks.py`) behave the same.
PY ?= python
PHASE ?= 0

.PHONY: setup dev migrate seed-demo lint typecheck test-unit test-integration test-e2e build smoke check-gate
setup dev migrate seed-demo lint typecheck test-unit test-integration test-e2e build smoke:
	$(PY) tasks.py $@

check-gate:
	$(PY) tasks.py check-gate $(PHASE)
