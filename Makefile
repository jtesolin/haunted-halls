.PHONY: help install dev build start lint typecheck test clean \
	docker-build docker-up docker-down docker-logs docker-ps docker-config \
	debug-build debug-up debug-down debug-logs debug-config \
	docker-reset-db

PORT ?= 3000

COMPOSE = docker compose
DEBUG_COMPOSE = docker compose -f docker-compose.yml -f docker-compose.debug.yml

help:
	@echo "Local app:     install, dev, build, start, lint, typecheck, test, clean"
	@echo "Compose stack: docker-build, docker-up, docker-down, docker-logs, docker-ps, docker-config"
	@echo "Debug stack:   debug-build, debug-up, debug-down, debug-logs, debug-config"
	@echo "Destructive:   docker-reset-db (deletes the persistent SQLite volume)"

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
	$(DEBUG_COMPOSE) up

debug-down:
	$(DEBUG_COMPOSE) down

debug-logs:
	$(DEBUG_COMPOSE) logs -f

debug-config:
	$(DEBUG_COMPOSE) config

# Destructive: removes the engine-data volume and all local campaign data.
docker-reset-db:
	$(COMPOSE) down -v