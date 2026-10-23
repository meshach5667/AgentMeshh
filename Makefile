.PHONY: help dev dev-up dev-down dev-logs dev-restart db-migrate db-revision db-downgrade db-reset server-install server-run server-lint server-format server-typecheck server-test server-test-cov agent-install agent-run agent-register e2e client-install client-dev client-build client-lint client-test client-e2e test test-server test-client test-e2e docker-build docker-clean ci lint typecheck

help:
	@echo "Available commands:"
	@echo "Development:"
	@echo "  make dev              - Start all services with docker-compose"
	@echo "  make dev-up           - Start services in background"
	@echo "  make dev-down         - Stop services"
	@echo "  make dev-logs         - View logs"
	@echo "  make dev-restart      - Restart all services"
	@echo ""
	@echo "Database:"
	@echo "  make db-migrate       - Run alembic migrations"
	@echo "  make db-revision MSG  - Create new migration"
	@echo "  make db-downgrade     - Rollback last migration"
	@echo "  make db-reset         - Reset database"
	@echo ""
	@echo "Server:"
	@echo "  make server-install   - Install Python deps"
	@echo "  make server-run       - Run server locally"
	@echo "  make server-lint      - Run ruff linter"
	@echo "  make server-format    - Run ruff formatter"
	@echo "  make server-typecheck - Run mypy"
	@echo "  make server-test      - Run pytest"
	@echo "  make server-test-cov  - Run pytest with coverage"
	@echo ""
	@echo "Node Agent:"
	@echo "  make agent-install    - Install node agent deps"
	@echo "  make agent-run        - Run node agent locally"
	@echo "  make agent-register TOKEN=... - Enroll this machine as a worker"
	@echo "  make e2e              - End-to-end deployment check against a running control plane"
	@echo ""
	@echo "Client:"
	@echo "  make client-install   - npm install"
	@echo "  make client-dev       - npm run dev"
	@echo "  make client-build     - npm run build"
	@echo "  make client-lint      - npm run lint"
	@echo "  make client-test      - Run frontend tests"
	@echo "  make client-e2e       - Run Playwright tests"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build     - Build all images"
	@echo "  make docker-clean     - Clean up"

# Development
dev:
	docker-compose up

dev-up:
	docker-compose up -d

dev-down:
	docker-compose down

dev-logs:
	docker-compose logs -f

dev-restart:
	docker-compose restart

# Database
db-migrate:
	cd server && alembic upgrade head

db-revision:
	cd server && alembic revision --autogenerate -m "$(MSG)"

db-downgrade:
	cd server && alembic downgrade -1

db-reset:
	cd server && alembic downgrade base && alembic upgrade head

# Server
server-install:
	cd server && pip install -r requirements.txt

server-run:
	cd server && uvicorn app.main:app --reload

server-lint:
	cd server && ruff check .

server-format:
	cd server && ruff format .

server-typecheck:
	cd server && mypy app/ --ignore-missing-imports

server-test:
	cd server && pytest tests/ -v

server-test-cov:
	cd server && pytest tests/ -v --cov=app --cov-report=xml

# Node Agent
agent-install:
	cd server && pip install -r requirements-worker.txt

agent-run:
	cd server && python -m node_agent run

agent-register:
	cd server && python -m node_agent enroll --token $(TOKEN)

e2e:
	cd server && python scripts/e2e_ollama.py --api $${API:-http://127.0.0.1:8000} --model $${MODEL:-smollm2:135m}

# Client
client-install:
	cd client && npm install

client-dev:
	cd client && npm run dev

client-build:
	cd client && npm run build

client-lint:
	cd client && npm run lint

client-test:
	cd client && npm test

client-e2e:
	cd client && npx playwright test

# Testing
test: test-server test-client test-e2e

test-server: server-test

test-client: client-test

test-e2e: client-e2e

# Docker
docker-build:
	docker-compose build

docker-clean:
	docker-compose down -v --rmi all

# CI
ci: lint typecheck test

lint: server-lint client-lint

typecheck: server-typecheck
