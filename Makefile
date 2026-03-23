# =============================================================================
# GLOBAL VARIABLES
# =============================================================================
.DEFAULT_GOAL := help
SHELL := /bin/bash

PROJECT_NAME := SentryMode
VERSION      := $(shell git describe --tags --always --dirty 2>/dev/null || echo "0.1.0")
COMMIT_HASH  := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_TIME   := $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")
SRC_DIR      := src
TEST_DIR     := tests
UV           := uv
PYTHON       := $(UV) run python
PYTEST       := $(UV) run pytest
RUFF         := $(UV) run ruff
PRECOMMIT    := $(UV) run pre-commit
DOCKER       := docker
COMPOSE      := docker compose
IMAGE_NAME   := sentrymode:latest
SERVICE_NAME := sentrymode
ENV_FILE     := .env.example

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
define print_header
	@echo ""
	@echo "==============================================================="
	@echo " $(1)"
	@echo "==============================================================="
endef

# =============================================================================
# TARGETS
# =============================================================================

.PHONY: help
help:  ## Display this help screen
	$(call print_header,SentryMode - A multi-factor monitoring toolkit for market signals.)
	@echo "Version: $(VERSION) ($(COMMIT_HASH))"
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

.PHONY: check
check: format lint test ## Full check pipeline: format, lint, test

.PHONY: ci
ci: clean check ## Full CI pipeline: clean, format, lint, test

##@ Development

.PHONY: init
init: ## Initialize the project and install dependencies
	$(call print_header,Installing Dependencies)
	@$(UV) sync --all-extras --dev
	@echo "Environment initialized."

.PHONY: format
format: ## Format code and sort imports
	$(call print_header,Formatting Code)
	@$(RUFF) format .
	@$(RUFF) check --select I --fix .
	@$(PYTHON) scripts/add_trailing_comma_to_params.py src tests

.PHONY: lint
lint: ## Run read-only lint checks
	$(call print_header,Running Static Analysis)
	@$(RUFF) format --check .
	@$(RUFF) check .

.PHONY: pre-commit
pre-commit: ## Run pre-commit hooks across the repository
	$(call print_header,Running Pre-commit Checks)
	@$(PRECOMMIT) run --all-files

##@ Testing & execution

.PHONY: test
test: ## Run unit tests with coverage
	$(call print_header,Running Tests)
	@$(PYTEST) -vv --cov=$(SRC_DIR) --cov-report=html --cov-report=term-missing $(TEST_DIR)

.PHONY: run
run: ## Run the package entrypoint
	$(call print_header,Running sentrymode)
	@$(UV) run sentrymode --help

##@ Docker & Compose

.PHONY: docker-build
docker-build: ## Build Docker image (IMAGE_NAME=sentrymode:latest)
	$(call print_header,Building Docker Image)
	@$(DOCKER) build -t $(IMAGE_NAME) .

.PHONY: compose-up
compose-up: ## Start service in background via compose.yaml
	$(call print_header,Starting Compose Stack)
	@$(COMPOSE) up -d $(SERVICE_NAME)

.PHONY: compose-down
compose-down: ## Stop and remove compose services
	$(call print_header,Stopping Compose Stack)
	@$(COMPOSE) down

.PHONY: compose-logs
compose-logs: ## Tail logs from the compose service
	$(call print_header,Tailing Compose Logs)
	@$(COMPOSE) logs -f --tail=200 $(SERVICE_NAME)

.PHONY: compose-ps
compose-ps: ## Show compose service status
	$(call print_header,Compose Service Status)
	@$(COMPOSE) ps

.PHONY: compose-restart
compose-restart: ## Restart compose service
	$(call print_header,Restarting Compose Service)
	@$(COMPOSE) restart $(SERVICE_NAME)

##@ Build & Release

.PHONY: build
build: ## Build standalone binary with PyInstaller (output: dist/sentrymode)
	$(call print_header,Building Standalone Binary)
	@$(UV) run pyinstaller project.spec --clean --noconfirm
	@echo "Binary built: dist/sentrymode"

.PHONY: dist
dist: ## Build Python sdist + wheel for PyPI
	$(call print_header,Building Python Distribution)
	@$(UV) build
	@echo "Distribution packages:"
	@ls -lh dist/*.whl dist/*.tar.gz 2>/dev/null || true

.PHONY: release-tag
release-tag: ## Create and push a git tag to trigger the release workflow (use: make release-tag VERSION=v1.2.3)
	$(call print_header,Creating Release Tag)
	@test -n "$(VERSION)" || (echo "Usage: make release-tag VERSION=v1.2.3" && exit 1)
	@git tag -a $(VERSION) -m "Release $(VERSION)"
	@git push origin $(VERSION)
	@echo "Tag $(VERSION) pushed — GitHub Actions release workflow triggered."

##@ Clean

.PHONY: clean
clean: ## Clean build artifacts and caches
	$(call print_header,Cleaning up)
	@rm -rf dist build *.egg-info htmlcov .coverage
	@find . -depth -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -depth -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -depth -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -depth -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
