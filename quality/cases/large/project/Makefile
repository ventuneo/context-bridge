install:
	python3 -m venv .venv
dev:
	npm run dev
test:
	python3 -m unittest
lint:
	ruff check .
test-integration:
	python3 -m unittest discover -s tests/integration
backup:
	./scripts/backup.sh
restore:
	./scripts/restore.sh
