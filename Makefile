.PHONY: test lint validate bootstrap source-verify source-checkout test-bundle-contract images-build images-load cluster-up cluster-down deploy smoke diagnostics compose-up compose-down

test:
	python3 -m unittest discover -s tests/contract -p 'test_*.py' -v

lint:
	shellcheck scripts/*.sh tests/e2e/*.sh
	helm lint charts/coderushoj-infra
	helm lint charts/coderushoj

validate: test lint

bootstrap:
	./scripts/bootstrap.sh

source-verify:
	./scripts/verify-source-lock.py validate

source-checkout:
	./scripts/checkout-sources.sh

test-bundle-contract: source-checkout
	./scripts/verify-test-bundle-contract.sh

images-build:
	./scripts/build-dev-images.sh

images-load:
	./scripts/load-dev-images.sh

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
