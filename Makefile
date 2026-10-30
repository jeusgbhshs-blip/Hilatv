.PHONY: up down ps test lint accept-t01 accept-t02 accept-t03 accept-t04 accept-t05 accept-t06 accept-t07 accept-t08 accept-t09 accept-t10 accept-t11 accept-t12 accept-t15 accept-t17 accept-t18 accept-t21 accept-t25 install api

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

accept-t06:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t06.sh

accept-t07:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t07.sh

accept-t08:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t08.sh

accept-t09:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t09.sh

accept-t10:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t10.sh

accept-t11:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t11.sh

accept-t12:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t12.sh

accept-t15:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t15.sh

accept-t17:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t17.sh

accept-t18:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t18.sh

accept-t21:
	ENV_FILE=$(ENV_FILE) bash $(ROOT)/infra/scripts/accept_t21.sh

accept-t25:
	$(PYTHON) -m templates.validate
	$(PYTHON) -m pytest tests/test_t25_templates.py workers/nodes/n01_brief/tests/test_industries.py workers/nodes/n05_storyboard/tests/test_presets.py -q --tb=short

api:
	$(PYTHON) -m uvicorn app.main:app --app-dir $(ROOT)/apps/api --host 0.0.0.0 --port 8000
