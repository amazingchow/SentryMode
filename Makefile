# =============================================================================
# GLOBAL VARIABLES
# =============================================================================
.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash -o pipefail -o errexit

PROJECT_NAME        := SentryMode
VERSION             := $(shell git describe --tags --always --dirty 2>/dev/null || echo "0.1.0")
COMMIT_HASH         := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_TIME          := $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")
SRC_DIR             := src
TEST_DIR            := tests
UV                  := uv
PYTHON              := $(UV) run python
COVERAGE            := $(UV) run coverage
RUFF                := $(UV) run ruff
PRECOMMIT           := $(UV) run pre-commit
SAFETY              := $(UV) run safety
DOCKER              := docker
COMPOSE             := docker compose
IMAGE_NAME          := sentrymode:latest
SERVICE_NAME        := sentrymode
ENV_FILE            := .env
RUN_NETWORK         ?= 0
PYTEST_ARGS         ?=
PYTEST_NETWORK_ARGS := $(if $(filter 1 true TRUE yes YES,$(RUN_NETWORK)),--run-network,)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
# Inner width between ╔/╗ and ╚/╝ (must match the ═ run length).
PRINT_HEADER_INNER_WIDTH := 68

define print_header
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════════════╗"
	@t='$(subst ','\'',$(1))'; w=$(PRINT_HEADER_INNER_WIDTH); \
	l=$$(( ($$w - $${#t}) / 2 )); r=$$(( $$w - $${#t} - $$l )); \
	printf '%*s%s%*s\n' "$$l" '' "$$t" "$$r" ''
	@echo "╚════════════════════════════════════════════════════════════════════╝"
endef

define print_log
	@echo "🚀 $(1)"
endef

# =============================================================================
# TARGETS
# =============================================================================

.PHONY: help
help:  ## Display this help screen
	$(call print_header,SentryMode)
	@echo "A multi-factor monitoring toolkit for market signals."
	@echo ""
	@echo "Version@$(VERSION) ($(COMMIT_HASH))"
	@awk 'BEGIN {FS = ":.*##"; printf "\nCommands:\n  make \033[32m<target>\033[0m\n\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[32m%-20s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1;32m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Workflows

.PHONY: check
check: format lint lockfile-update pre-commit ## Full check pipeline: format, lint, lockfile-update, pre-commit

.PHONY: ci
ci: clean check test check-safety ## Full CI pipeline: clean, format, lint, test, check-safety

##@ Development

download-uv: ## Download uv
	$(call print_log,Downloading uv...)
	@curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "✅ uv downloaded."

.PHONY: install
install: ## Initialize the project and install dependencies
	$(call print_log,Installing Dependencies...)
	@$(UV) sync --all-extras --dev
	@echo "✅ Environment initialized."

.PHONY: lockfile-update
lockfile-update: ## Update the lockfile
	$(call print_log,Updating Lockfile...)
	@$(UV) lock
	@echo "✅ Lockfile updated."

.PHONY: format
format: ## Format code and sort imports
	$(call print_log,Formatting Code...)
	@$(RUFF) format .
	@$(RUFF) check --select I --fix .
	@$(PYTHON) scripts/add_trailing_comma_to_params.py src tests

.PHONY: lint
lint: ## Run read-only lint checks
	$(call print_log,Running Static Analysis...)
	@$(RUFF) format --check .
	@$(RUFF) check .

.PHONY: pre-commit
pre-commit: ## Run pre-commit hooks across the repository
	$(call print_log,Running Pre-commit Checks...)
	@$(PRECOMMIT) run --all-files

.PHONY: check-safety
check-safety:	## Run safety checks on dependencies
	$(call print_log,Running Safety Checks...)
	@$(SAFETY) scan --full-report
	@echo "✅ Safety Checks completed."

##@ Testing & execution

.PHONY: test
test: ## Run unit tests with coverage (set RUN_NETWORK=1 to include network smoke tests)
	$(call print_log,Running Tests...)
	@$(COVERAGE) erase
	@$(COVERAGE) run -m pytest -vv $(TEST_DIR) $(PYTEST_NETWORK_ARGS) $(PYTEST_ARGS)
	@$(COVERAGE) report

.PHONY: run
run: ## Run the package entrypoint
	$(call print_log,Running sentrymode...)
	@$(UV) run sentrymode --help

##@ Docker & Compose

.PHONY: docker-build
docker-build: ## Build Docker image (IMAGE_NAME=sentrymode:latest)
	$(call print_log,Building Docker Image...)
	@$(DOCKER) build -t $(IMAGE_NAME) .

.PHONY: compose-up
compose-up: ## Start service in background via compose.yaml
	$(call print_log,Starting Compose Stack...)
	@$(COMPOSE) up -d $(SERVICE_NAME)

.PHONY: compose-down
compose-down: ## Stop and remove compose services
	$(call print_log,Stopping Compose Stack...)
	@$(COMPOSE) down

.PHONY: compose-logs
compose-logs: ## Tail logs from the compose service
	$(call print_log,Tailing Compose Logs...)
	@$(COMPOSE) logs -f --tail=200 $(SERVICE_NAME)

.PHONY: compose-ps
compose-ps: ## Show compose service status
	$(call print_log,Compose Service Status...)
	@$(COMPOSE) ps

.PHONY: compose-restart
compose-restart: ## Restart compose service
	$(call print_log,Restarting Compose Service...)
	@$(COMPOSE) restart $(SERVICE_NAME)

##@ Build & Release

.PHONY: build
build: ## Build standalone binary with PyInstaller (output: dist/sentrymode)
	$(call print_log,Building Standalone Binary...)
	@$(UV) run pyinstaller project.spec --clean --noconfirm
	@echo "✅ Binary built: dist/sentrymode"

.PHONY: dist
dist: ## Build Python sdist + wheel for PyPI
	$(call print_log,Building Python Distribution...)
	@$(UV) build
	@echo "✅ Distribution packages:"
	@ls -lh dist/*.whl dist/*.tar.gz 2>/dev/null || true

.PHONY: release-tag
release-tag: ## Create and push a git tag to trigger the release workflow (use: make release-tag VERSION=v1.2.3)
	$(call print_log,Creating Release Tag...)
	@test -n "$(VERSION)" || (echo "Usage: make release-tag VERSION=v1.2.3" && exit 1)
	@git tag -a $(VERSION) -m "Release $(VERSION)"
	@git push origin $(VERSION)
	@echo "✅ Tag $(VERSION) pushed — GitHub Actions release workflow triggered."

##@ Clean

.PHONY: clean
clean: ## Clean build artifacts and caches
	$(call print_log,Cleaning up...)
	@rm -rf .DS_Store dist build *.egg-info htmlcov .coverage coverage.xml
	@find . -depth -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	@find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
	@find . -depth -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -depth -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -depth -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
