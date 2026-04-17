.PHONY: install install-dev lint test run-api run-ui simulate demo helm-lint docker-build docker-run clean

PYTHON := python3
PIP := pip3
PORT := 8000
UI_PORT := 8501
IMAGE := ai-k8s-sre-operator:latest

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

lint:
	ruff check . --fix
	ruff format .

test:
	DEMO_MODE=1 DATABASE_URL=sqlite:///./test_sre.db $(PYTHON) -m pytest tests/ -v --tb=short

test-cov:
	DEMO_MODE=1 DATABASE_URL=sqlite:///./test_sre.db $(PYTHON) -m pytest tests/ -v --cov=. --cov-report=term-missing

run-api:
	uvicorn api.main:app --host 0.0.0.0 --port $(PORT) --reload

run-api-demo:
	DEMO_MODE=1 uvicorn api.main:app --host 0.0.0.0 --port $(PORT) --reload

run-ui:
	API_BASE_URL=http://localhost:$(PORT) streamlit run ui/streamlit_app.py --server.port $(UI_PORT)

simulate:
	DEMO_MODE=1 $(PYTHON) -m cli.main simulate --type crashloop

# One-command demo: start API, wait for it to be ready, then launch UI and inject incidents
demo:
	@echo "Starting AI K8s SRE Operator demo..."
	@echo "Step 1/3: Starting API server in demo mode (background)"
	DEMO_MODE=1 uvicorn api.main:app --host 0.0.0.0 --port $(PORT) &
	@echo "Waiting for API to be ready..."
	@sleep 3
	@until curl -sf http://localhost:$(PORT)/health > /dev/null 2>&1; do sleep 1; done
	@echo "Step 2/3: API is ready. Injecting demo incidents..."
	DEMO_MODE=1 $(PYTHON) -m cli.main simulate --type crashloop
	DEMO_MODE=1 $(PYTHON) -m cli.main simulate --type oomkilled
	DEMO_MODE=1 $(PYTHON) -m cli.main simulate --type pending
	@echo "Step 3/3: Starting Streamlit dashboard..."
	@echo ""
	@echo "Dashboard: http://localhost:$(UI_PORT)"
	@echo "API docs:  http://localhost:$(PORT)/docs"
	@echo ""
	API_BASE_URL=http://localhost:$(PORT) streamlit run ui/streamlit_app.py --server.port $(UI_PORT)

simulate-oom:
	DEMO_MODE=1 $(PYTHON) -m cli.main simulate --type oomkilled

simulate-pending:
	DEMO_MODE=1 $(PYTHON) -m cli.main simulate --type pending

helm-lint:
	helm lint helm/ai-k8s-sre-operator

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker-compose up -d

docker-stop:
	docker-compose down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.db" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage

help:
	@echo "Available targets:"
	@echo "  install      - Install production dependencies"
	@echo "  install-dev  - Install dev dependencies (includes pytest, ruff)"
	@echo "  lint         - Run ruff linter and formatter"
	@echo "  test         - Run all tests"
	@echo "  run-api      - Start FastAPI server on port $(PORT)"
	@echo "  run-api-demo - Start FastAPI in demo mode (no cluster needed)"
	@echo "  run-ui       - Start Streamlit dashboard on port $(UI_PORT)"
	@echo "  simulate     - Run CrashLoop simulation demo"
	@echo "  demo         - One-command demo: API + incidents + dashboard"
	@echo "  helm-lint    - Lint the Helm chart"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-run   - Start services via docker-compose"
	@echo "  clean        - Remove generated files"
