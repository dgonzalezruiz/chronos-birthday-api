PYTHON        := python3
VENV          := .venv
VENV_BIN      := $(VENV)/bin
APP_NAME      := chronos-birthday-api
IMAGE_TAG     := local
IMAGE         := $(APP_NAME):$(IMAGE_TAG)
PORT          := 8000

CLUSTER_NAME  := chronos-local
HELM_CHART    := helm/$(APP_NAME)
HELM_RELEASE  := $(APP_NAME)
NAMESPACE     := default

.PHONY: all venv install test run docker-build cluster-up metrics-deploy k8s-deploy test-e2e cluster-down e2e clean

all: unit-tests e2e

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(VENV_BIN)/pip install --upgrade pip

venv: $(VENV)/bin/activate

install: venv
	$(VENV_BIN)/pip install -r app/requirements.txt
	@if [ -f tests/requirements.txt ]; then $(VENV_BIN)/pip install -r tests/requirements.txt; fi

unit-tests: install
	PYTHONPATH=. $(VENV_BIN)/pytest tests/ -v --cov=app --cov-report=term-missing

run: install
	PYTHONPATH=. $(VENV_BIN)/uvicorn app.main:app --host 0.0.0.0 --port $(PORT) --reload

docker-build:
	docker build -t $(IMAGE) ./app

cluster-up:
	@if ! kind get clusters 2>/dev/null | grep -q "^$(CLUSTER_NAME)$$"; then \
		printf 'kind: Cluster\napiVersion: kind.x-k8s.io/v1alpha4\nnodes:\n- role: control-plane\n- role: worker\n' | \
			kind create cluster --name $(CLUSTER_NAME) --config - && \
		kubectl wait --for=condition=Ready nodes --all --timeout=120s; \
	fi

metrics-deploy:
	kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
	kubectl patch deployment metrics-server -n kube-system --type='json' -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'

k8s-deploy: docker-build cluster-up
	kind load docker-image $(IMAGE) --name $(CLUSTER_NAME)
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) \
		--namespace $(NAMESPACE) \
		--set image.repository=$(APP_NAME) \
		--set image.tag=$(IMAGE_TAG) \
		--set image.pullPolicy=Never \
		--wait --timeout 120s

test-e2e:
	@kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=$(APP_NAME) --timeout=60s -n $(NAMESPACE)
	@( \
		kubectl port-forward svc/$(HELM_RELEASE) $(PORT):80 -n $(NAMESPACE) --address 127.0.0.1 > /dev/null 2>&1 & \
		PF_PID=$$!; \
		trap "kill -9 $$PF_PID 2>/dev/null || true" EXIT INT TERM; \
		for i in $$(seq 1 15); do \
			if curl -sf http://127.0.0.1:$(PORT)/healthz > /dev/null 2>&1; then break; fi; \
			sleep 1; \
		done; \
		STATUS=$$(curl -s -o /dev/null -w "%{http_code}" -X PUT http://127.0.0.1:$(PORT)/hello/Alice \
			-H "Content-Type: application/json" -d '{"dateOfBirth": "1990-01-01"}'); \
		[ "$$STATUS" = "204" ] || { echo "PUT Alice failed: $$STATUS"; exit 1; }; \
		RESP=$$(curl -s http://127.0.0.1:$(PORT)/hello/Alice); \
		echo "$$RESP" | grep -q "Your birthday is in" || { echo "Unexpected response: $$RESP"; exit 1; }; \
		STATUS_BAD=$$(curl -s -o /dev/null -w "%{http_code}" -X PUT http://127.0.0.1:$(PORT)/hello/Alice123 \
			-H "Content-Type: application/json" -d '{"dateOfBirth": "1990-01-01"}'); \
		[ "$$STATUS_BAD" = "400" ] || { echo "Bad username check failed: $$STATUS_BAD"; exit 1; }; \
		STATUS_HEALTH=$$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$(PORT)/healthz); \
		[ "$$STATUS_HEALTH" = "200" ] || { echo "Healthcheck failed: $$STATUS_HEALTH"; exit 1; }; \
		echo "Live E2E smoke tests completed successfully."; \
	)

cluster-down:
	@kind delete cluster --name $(CLUSTER_NAME) 2>/dev/null || true

e2e: k8s-deploy metrics-deploy test-e2e cluster-down

clean: cluster-down
	rm -rf $(VENV) .pytest_cache .coverage app/__pycache__ tests/__pycache__
