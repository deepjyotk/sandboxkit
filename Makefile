# SandboxKit — kind cluster + images pulled from Docker Hub
#
#   make push    # build images and push to Docker Hub (run before first deploy)
#   make setup   # kind + infra
#   make kind    # create kind cluster only
#   make infra   # deploy control plane + ingress (pulls images from registry)
#   make clean   # delete kind cluster + kind volumes only
#   make clean-docker-hub-template-images   # remove local Docker Hub image copies
#   make build-and-run-ui   # build test-runner UI (proxies API to ingress on :80)
#
# Requires .env with DOCKERHUB_USER=your-dockerhub-username

ifneq (,$(wildcard .env))
include .env
export
endif

KIND_CLUSTER   ?= sandbox
KIND_CONFIG    := infra/kind/cluster.yaml
KUSTOMIZE_BASE := infra/kustomize/base
KUBE_CONTEXT   := kind-$(KIND_CLUSTER)
INGRESS_URL    := https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.3/deploy/static/provider/kind/deploy.yaml

DOCKERHUB_USER ?=
IMAGE_TAG      ?= latest

IMG_SANDBOXKIT       = $(DOCKERHUB_USER)/sandboxkit:$(IMAGE_TAG)
IMG_TEMPLATE_PY = $(DOCKERHUB_USER)/sandboxkit-py-template:$(IMAGE_TAG)
IMG_TEMPLATE_JS = $(DOCKERHUB_USER)/sandbox-js-template:$(IMAGE_TAG)

KUBECTL      := kubectl --context $(KUBE_CONTEXT)
BUILD_SCRIPT := ./scripts/build-template-images.sh

UI_PORT ?= 5173

DO_DROPLET_IP ?= $(shell doctl compute droplet list --format Name,PublicIPv4 --no-header 2>/dev/null | awk '/sandbox-kata/{print $$2}')
DO_SSH_KEY    ?= $(HOME)/.ssh/id_ed25519_do

.PHONY: setup kind infra push clean clean-docker-hub-template-images check-dockerhub \
	check-images-on-registry build-and-run-ui do-setup-droplet do-deploy-do

setup: kind infra build-and-run-ui

kind:
	@if kubectl config get-contexts -o name 2>/dev/null | grep -qx '$(KUBE_CONTEXT)'; then \
		echo "==> Kind cluster '$(KIND_CLUSTER)' already exists"; \
	else \
		echo "==> Creating kind cluster '$(KIND_CLUSTER)'"; \
		kind create cluster --config $(KIND_CONFIG) --name $(KIND_CLUSTER); \
	fi
	$(KUBECTL) cluster-info

push: check-dockerhub
	@echo "==> Building and pushing images to docker.io/$(DOCKERHUB_USER)"
	DOCKERHUB_USER="$(DOCKERHUB_USER)" IMAGE_TAG="$(IMAGE_TAG)" PUSH=1 $(BUILD_SCRIPT)

# DigitalOcean droplet: k3s + Kata (run on Mac; SSHs to sandbox-kata)
do-setup-droplet:
	@test -n "$(DO_DROPLET_IP)" || (echo "Set DO_DROPLET_IP or create droplet sandbox-kata" && exit 1)
	scp -i $(DO_SSH_KEY) digital-ocean/setup-droplet.sh root@$(DO_DROPLET_IP):/root/setup-droplet.sh
	ssh -i $(DO_SSH_KEY) root@$(DO_DROPLET_IP) 'bash /root/setup-droplet.sh'

# Push images + deploy Sandboxkit to DO k3s (after do-setup-droplet)
do-deploy-do:
	DROPLET_IP=$(DO_DROPLET_IP) SSH_KEY=$(DO_SSH_KEY) ./digital-ocean/deploy-sandboxkit.sh

infra:
	@echo "==> Installing ingress-nginx"
	$(KUBECTL) apply -f $(INGRESS_URL)
	$(KUBECTL) wait --namespace ingress-nginx \
		--for=condition=ready pod \
		--selector=app.kubernetes.io/component=controller \
		--timeout=180s
	@echo "==> Deploying sandboxkit (nodes pull from registry)"
	$(KUBECTL) apply -k $(KUSTOMIZE_BASE)
	$(KUBECTL) set image deployment/sandboxkit \
		sandboxkit=$(IMG_SANDBOXKIT) \
		-n sandboxes
	$(KUBECTL) set env deployment/sandboxkit -n sandboxes \
		TEMPLATE_PY_IMAGE=$(IMG_TEMPLATE_PY) \
		TEMPLATE_JS_IMAGE=$(IMG_TEMPLATE_JS) \
		SANDBOX_IMAGE_PULL_POLICY=IfNotPresent
	$(KUBECTL) rollout restart deployment/sandboxkit -n sandboxes
	$(KUBECTL) rollout status deployment/sandboxkit -n sandboxes --timeout=180s
	@echo "==> Ready: http://127.0.0.1/health  |  http://127.0.0.1/docs"
	@echo "    Pulling: $(IMG_SANDBOXKIT)"

clean:
	@echo "==> Deleting kind cluster '$(KIND_CLUSTER)'"
	-kind delete cluster --name $(KIND_CLUSTER) 2>/dev/null || true
	@echo "==> Removing kind-related Docker volumes"
	@vols=$$(docker volume ls -q --filter label=io.x-k8s.kind.cluster=$(KIND_CLUSTER) 2>/dev/null); \
		if [ -n "$$vols" ]; then echo "$$vols" | xargs docker volume rm 2>/dev/null || true; fi
	@echo "==> Clean complete (cluster only; use make clean-docker-hub-template-images for local image copies)"

clean-docker-hub-template-images: check-dockerhub
	@echo "==> Removing local Docker Hub image copies for $(DOCKERHUB_USER)"
	@for img in $(IMG_SANDBOXKIT) $(IMG_TEMPLATE_PY) $(IMG_TEMPLATE_JS); do \
		docker rmi -f "$$img" 2>/dev/null || true; \
	done
	@echo "==> Docker Hub local images removed (registry tags on hub are unchanged)"

check-dockerhub:
	@if [ -z "$(DOCKERHUB_USER)" ]; then \
		echo "ERROR: Set DOCKERHUB_USER in .env (copy from .env.example)"; \
		exit 1; \
	fi

# kind pulls from the registry at runtime — images must exist before make infra / make setup
check-images-on-registry:
	@echo "==> Checking registry images exist (run 'make push' first if missing)"
	@for img in $(IMG_SANDBOXKIT) $(IMG_TEMPLATE_PY) $(IMG_TEMPLATE_JS); do \
		if ! docker manifest inspect "$$img" >/dev/null 2>&1; then \
			echo "ERROR: $$img not found on Docker Hub. Run: docker login && make push"; \
			exit 1; \
		fi; \
		echo "  ok $$img"; \
	done

build-and-run-ui:
	@echo "==> Building UI (npm)"
	cd ui && npm install && npm run build
	@echo "==> UI http://127.0.0.1:$(UI_PORT) (API via ingress at http://127.0.0.1)"
	@echo "    Requires: make push && make infra"
	cd ui && npm run preview -- --host 127.0.0.1 --port $(UI_PORT)
