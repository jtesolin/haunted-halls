.PHONY: help install dev build start lint typecheck test clean \
	docker-build docker-up docker-down docker-logs docker-ps docker-config docker-migrate \
	debug-build debug-up debug-down debug-logs debug-config \
	docker-reset-db

PORT ?= 3000

COMPOSE = docker compose
DEBUG_COMPOSE = docker compose -f docker-compose.yml -f docker-compose.debug.yml

help:
	@echo "Local development (Next.js):"
	@echo "  install           Install npm dependencies"
	@echo "  dev               Start Next.js dev server (default port 3000)"
	@echo "  build             Build production bundles"
	@echo "  start             Run production-built Next.js server"
	@echo "  lint              Run ESLint"
	@echo "  typecheck         Run TypeScript type checking"
	@echo "  test              Run Vitest test suite"
	@echo "  clean             Remove .next build directory"
	@echo ""
	@echo "Docker Compose Stack (includes PostgreSQL, engine, frontend):"
	@echo "  docker-build      Build Compose application images"
	@echo "  docker-up         Start the full stack (postgres → migrate → engine → frontend)"
	@echo "                    PostgreSQL and migrations run automatically"
	@echo "  docker-down       Stop/remove containers and networks (preserves postgres-data volume)"
	@echo "  docker-ps         Show container status"
	@echo "  docker-logs       Follow stack logs (postgres, migrate, engine, frontend)"
	@echo "  docker-config     Render and validate Compose configuration"
	@echo "  docker-migrate    Rebuild engine/migration image and run one-shot migration service"
	@echo "                    Use after: pulling new migrations while stack is already running"
	@echo "                    Rebuilds image from current local source; PostgreSQL/engine stay running"
	@echo ""
	@echo "Destructive:"
	@echo "  docker-reset-db   DESTRUCTIVE: Stop stack and delete postgres-data volume"
	@echo "                    Next 'docker-up' will recreate database and run all migrations"
	@echo ""
	@echo "Debug Stack (adds bind mounts, debuggers, debug Dockerfile stages):"
	@echo "  debug-build       Build debug stack images"
	@echo "  debug-up          Start debug stack with source bind mounts and debuggers"
	@echo "  debug-down        Stop debug stack"
	@echo "  debug-logs        Follow debug stack logs"
	@echo "  debug-config      Render debug stack configuration"

install:
	npm install

dev:
	npm run dev -- -p $(PORT)

build:
	npm run build

start:
	npm run start

lint:
	npm run lint

typecheck:
	npm run typecheck

clean:
	rm -rf .next

test:
	npm run test

docker-build:
	$(COMPOSE) build

docker-up:
	$(COMPOSE) up -d

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f

docker-ps:
	$(COMPOSE) ps

docker-config:
	$(COMPOSE) config

debug-build:
	$(DEBUG_COMPOSE) build

debug-up:
	$(DEBUG_COMPOSE) up --build

debug-down:
	$(DEBUG_COMPOSE) down

debug-logs:
	$(DEBUG_COMPOSE) logs -f

debug-config:
	$(DEBUG_COMPOSE) config

docker-migrate:
	$(COMPOSE) run --rm --build migrate

# Destructive: removes Compose volumes (including postgres-data) and all local campaign data.
docker-reset-db:
	$(COMPOSE) down -v