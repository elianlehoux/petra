.PHONY: setup build run demo test benchmark clean docker-build docker-run help

setup:
	@echo "Installing dependencies..."
	@pip install -r python/requirements.txt -r python/requirements-dev.txt

build:
	@echo "Installing Python package..."
	@pip install -e python

run:
	@echo "Starting API server..."
	@python -m compiled_ai_router.cli serve

demo:
	@echo "Running demo showcase..."
	@python -m compiled_ai_router.cli demo

test:
	@echo "Running all tests..."
	@./run_tests.sh

benchmark:
	@echo "Running benchmark..."
	@./examples/benchmark.sh

clean:
	@echo "Cleaning build artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@rm -rf artifacts/*.py artifacts/*.json

docker-build:
	@docker build -t compiled-ai-router .

docker-run:
	@docker-compose up

help:
	@echo "Available commands:"
	@echo "  make setup         - install Python dependencies"
	@echo "  make build         - install the Python package (editable)"
	@echo "  make run           - start the API server"
	@echo "  make demo          - run the demo showcase"
	@echo "  make test          - run all tests"
	@echo "  make benchmark     - run the real benchmark"
	@echo "  make clean         - remove build artifacts"
	@echo "  make docker-build  - build Docker image"
	@echo "  make docker-run    - run via Docker Compose"
