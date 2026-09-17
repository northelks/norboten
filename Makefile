# Norboten — every workflow starts here. `make help` lists targets.
SHELL := /bin/bash
UV    ?= uv
RUN   := $(UV) run

.DEFAULT_GOAL := help

.PHONY: help
help: ## List targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Create the venv and install every workspace package
	$(UV) sync --all-packages

.PHONY: test
test: install ## Run the test suite
	$(RUN) pytest

.PHONY: test-db
test-db: ## Store and bus tests against real PostgreSQL and Redis in Docker (throwaway containers)
	docker run -d --rm --name norboten-test-db -e POSTGRES_USER=norboten -e POSTGRES_PASSWORD=norboten \
		-e POSTGRES_DB=norboten_test -p 127.0.0.1:55432:5432 postgres:17-alpine >/dev/null
	docker run -d --rm --name norboten-test-redis -p 127.0.0.1:56379:6379 redis:7-alpine >/dev/null
	@until docker exec norboten-test-db pg_isready -U norboten >/dev/null 2>&1; do sleep 1; done
	NORBOTEN_TEST_DATABASE_URL=postgresql://norboten:norboten@127.0.0.1:55432/norboten_test \
	NORBOTEN_TEST_REDIS_URL=redis://127.0.0.1:56379/0 \
		$(RUN) python -m pytest api/tests/test_stores.py api/tests/test_live.py; status=$$?; \
		docker stop norboten-test-db norboten-test-redis >/dev/null; exit $$status

.PHONY: release-check
release-check: ## Build the release wheels and test them, and install.sh, outside the checkout
	.github/scripts/release_check.sh

.PHONY: test-site
test-site: ## The site's terminal player and consultant fallback, in node
	@command -v node >/dev/null || { echo "node not installed; skipping the player checks"; exit 0; }
	node site/tests/term.test.mjs
	node site/tests/ask.test.mjs
	@command -v shellcheck >/dev/null && shellcheck -s sh site/static/install.sh || echo "shellcheck not installed; install.sh not linted"

.PHONY: lint
lint: install ## Ruff lint + format check, then static lab validation
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(MAKE) lint-labs

.PHONY: fmt
fmt: install ## Auto-fix lint and formatting
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

.PHONY: lint-labs
lint-labs: ## Validate every lab against docs/lab-spec.md (no VM needed)
	$(RUN) python -m norboten.labs.lint labs

.PHONY: schema
schema: ## Export JSON Schemas for lab.yaml and registry.yaml to docs/schema/
	$(RUN) python -m norboten.schema docs/schema
	$(RUN) python -m norboten_api.reference > docs/api-reference.md

.PHONY: image
image: ## Build a golden base image: make image IMAGE=alpine
	@test -n "$(IMAGE)" || { echo "usage: make image IMAGE=<rocky-10|ubuntu-26.04|alpine>"; exit 2; }
	$(RUN) python images/build.py $(IMAGE)

.PHONY: validate
validate: ## Solvability gate for one lab: make validate LAB=hello [IMAGE=alpine]
	@test -n "$(LAB)" || { echo "usage: make validate LAB=<lab> [IMAGE=<image>]"; exit 2; }
	$(RUN) norboten dev validate $(LAB) $(if $(IMAGE),--image $(IMAGE))

.PHONY: stack-up
stack-up: seed ## The whole server side on this laptop: site :8080, API :8000, Grafana :3000
	@test -f deploy/.env.local || { cp deploy/.env.example deploy/.env.local; \
		sed -i.bak -e 's/^NORBOTEN_DOMAIN=.*/NORBOTEN_DOMAIN=localhost/' \
		-e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$$(openssl rand -hex 16)/" \
		-e "s/^GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$$(openssl rand -hex 12)/" \
		deploy/.env.local; \
		rm -f deploy/.env.local.bak; echo "wrote deploy/.env.local with fresh passwords"; }
	NORBOTEN_SITE_API=http://localhost:8000 $(RUN) python site/build.py
	docker compose --env-file deploy/.env.local -f deploy/compose.yaml -f deploy/compose.local.yaml up -d --build
	@echo "site http://localhost:8080 · api http://localhost:8000 · grafana http://localhost:3000"
	@echo "the TUI against it:  NORBOTEN_API=http://localhost:8000 uv run norboten"

.PHONY: server-rehearsal
server-rehearsal: ## Rehearse the server deploy on a local Ubuntu VM: same playbook, compose and deploy.sh
	deploy/rehearsal.sh up

.PHONY: server-rehearsal-down
server-rehearsal-down: ## Delete the rehearsal VM
	deploy/rehearsal.sh down

.PHONY: jobs-rehearsal
jobs-rehearsal: ## Run every operational job end to end: real Claude Code, a scripted model, stand-ins for GitHub, Discord, Telegram
	$(RUN) python automation/rehearse.py

.PHONY: stack-down
stack-down: ## Stop the laptop stack (add V=1 to delete its data too)
	docker compose --env-file deploy/.env.local -f deploy/compose.yaml -f deploy/compose.local.yaml down $(if $(V),-v)

.PHONY: stack-logs
stack-logs: ## Follow the laptop stack's logs
	docker compose --env-file deploy/.env.local -f deploy/compose.yaml -f deploy/compose.local.yaml logs -f --tail 50

.PHONY: seed
seed: ## Generate the sample population the demo pages are drawn from (not real users)
	$(RUN) python seed/generate.py

.PHONY: captures
captures: ## Re-render the TUI screenshots the site shows (SVG, from the real app)
	$(RUN) python site/capture.py

.PHONY: site
site: seed ## Build the static site into site/dist
	$(RUN) python site/build.py

.PHONY: infra-validate
infra-validate: ## ansible syntax check + compose config + Caddyfile
	cd ansible && ansible-playbook --syntax-check -i localhost, playbooks/bootstrap.yml </dev/null
	cd ansible && ansible-playbook --syntax-check -i localhost, playbooks/server.yml </dev/null
	cp deploy/.env.example /tmp/norboten-env-check && sed -E -i.bak 's/^(POSTGRES_PASSWORD|GRAFANA_ADMIN_PASSWORD)=$$/\1=check/' /tmp/norboten-env-check
	docker compose --env-file /tmp/norboten-env-check -f deploy/compose.yaml config -q
	docker compose --env-file /tmp/norboten-env-check -f deploy/compose.yaml -f deploy/compose.local.yaml config -q
	docker run --rm -v "$$PWD/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" -e NORBOTEN_DOMAIN=norboten.org -e ACME_EMAIL=ops@norboten.org caddy:2.10-alpine caddy validate --config /etc/caddy/Caddyfile

.PHONY: server
server: ## Configure the server in ansible/inventory/production.yml (bootstrap it first: docs/deploy.md)
	cd ansible && ansible-playbook -i inventory/production.yml playbooks/server.yml --ask-vault-pass

.PHONY: bootstrap
bootstrap: ## First login to a new server as root: the deploy user and its key (KEY=~/.ssh/id_ed25519.pub)
	cd ansible && ansible-playbook -i inventory/production.yml playbooks/bootstrap.yml \
		-e ansible_user=root -e deploy_public_key="$$(cat $${KEY:-$$HOME/.ssh/id_ed25519.pub})"

.PHONY: check
check: lint test test-site ## Everything CI runs before the VM gate
