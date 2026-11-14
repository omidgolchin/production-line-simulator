PY ?= .venv/bin/python

.PHONY: test reproduce figures experiments

test:
	PYTHONPATH=src $(PY) -m pytest tests/ -q

experiments:
	PYTHONPATH=src $(PY) -m linesim.experiments

# Regenerate results/summary.md and every figure from saved outputs.
reproduce:
	PYTHONPATH=src $(PY) -m linesim.analyze

figures: reproduce
