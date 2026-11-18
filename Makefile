.PHONY: install check data build test lint

install:
	pip install -e ".[dev]"

check:
	python -m charles.cli check

data:
	python -m charles.cli usgs
	python -m charles.cli noaa

build:
	python -m charles.cli build

test:
	pytest

lint:
	ruff check .
