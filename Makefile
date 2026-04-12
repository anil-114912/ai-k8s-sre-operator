.PHONY: install install-dev lint test run-api run-ui simulate helm-lint docker-build docker-run clean

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
	DEMO_MODE=1 uvicorn api.main:app --host 0.0.0.0 --port $(PORT) --reload

run-ui:
	DEMO_MODE=1 API_BASE_URL=http://localhost:$(PORT) streamlit run ui/streamlit_app.py --server.port $(UI_PORT)

simulate:
	DEMO_MODE=1 $(PYTHON) -m cli.main simulate --type crashloop

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
	@echo "  run-ui       - Start Streamlit dashboard on port $(UI_PORT)"
	@echo "  simulate     - Run CrashLoop simulation demo"
	@echo "  helm-lint    - Lint the Helm chart"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-run   - Start services via docker-compose"
	@echo "  clean        - Remove generated files"
