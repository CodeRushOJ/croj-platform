.PHONY: test lint validate bootstrap cluster-up cluster-down deploy smoke diagnostics compose-up compose-down

test:
	python3 -m unittest discover -s tests/contract -p 'test_*.py' -v

lint:
	shellcheck scripts/*.sh
	helm lint charts/coderushoj-infra
	helm lint charts/coderushoj

validate: test lint

bootstrap:
	./scripts/bootstrap.sh

cluster-up:
	./scripts/cluster-up.sh

cluster-down:
	./scripts/cluster-down.sh

deploy:
	./scripts/deploy.sh

smoke:
	./tests/smoke/platform.sh

diagnostics:
	./scripts/diagnostics.sh

compose-up:
	./scripts/generate-secrets.sh --files-only
	docker compose up --detach --wait

compose-down:
	docker compose down
