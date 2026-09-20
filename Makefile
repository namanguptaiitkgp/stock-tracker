.PHONY: dev build up down logs test migrate seed clean install-hooks

# Development
dev:
	docker compose -f docker-compose.yml up --build

build:
	docker compose -f docker-compose.yml build

up:
	docker compose -f docker-compose.yml up -d

down:
	docker compose -f docker-compose.yml down

logs:
	docker compose -f docker-compose.yml logs -f

logs-backend:
	docker compose -f docker-compose.yml logs -f backend

logs-celery:
	docker compose -f docker-compose.yml logs -f celery-worker celery-beat

# Database
migrate:
	docker compose exec backend alembic upgrade head

migrate-create:
	docker compose exec backend alembic revision --autogenerate -m "$(msg)"

# Data
seed:
	docker compose exec backend python -m scripts.seed_instruments

# Testing
test:
	docker compose exec backend pytest -v

test-cov:
	docker compose exec backend pytest --cov=app --cov-report=html

# Cleanup
clean:
	docker compose -f docker-compose.yml down -v --remove-orphans

# Status
status:
	docker compose -f docker-compose.yml ps

# Install git hooks (auto-push on commit)
install-hooks:
	@cp scripts/git-hooks/post-commit .git/hooks/post-commit
	@chmod +x .git/hooks/post-commit
	@echo "installed .git/hooks/post-commit (auto-push). Suppress per-commit with NO_AUTO_PUSH=1."
