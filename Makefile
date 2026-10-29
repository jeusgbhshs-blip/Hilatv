.PHONY: up down ps test lint accept-t01 accept-t02 accept-t03 accept-t04 accept-t05 install api

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ENV_FILE := $(ROOT)/.env
ifeq ($(wildcard $(ENV_FILE)),)
ENV_FILE := $(ROOT)/.env.example
endif

export ENV_FILE

VENV_PY := $(ROOT)/.venv/bin/python
ifeq ($(wildcard $(VENV_PY)),)
PYTHON := python3
else
PYTHON := $(VENV_PY)
endif

up:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/compose.sh up -d --wait --wait-timeout 360

down:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/compose.sh down

ps:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/compose.sh ps

install:
	python3 -m venv $(ROOT)/.venv
	$(ROOT)/.venv/bin/pip install -U pip
	$(ROOT)/.venv/bin/pip install -e "$(ROOT)[dev]"

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	cd $(ROOT)/apps/web && npm run lint

accept-t01:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t01.sh

accept-t02:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t02.sh

accept-t03:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t03.sh

accept-t04:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t04.sh

accept-t05:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t05.sh

api:
	$(PYTHON) -m uvicorn app.main:app --app-dir $(ROOT)/apps/api --host 0.0.0.0 --port 8000
