.PHONY: install dev build start lint clean

PORT ?= 3000

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

clean:
	rm -rf .next

test:
	npm run test