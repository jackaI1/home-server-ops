# Common tasks. CI runs the same commands; see .github/workflows/serviceapp-operator.yml.
IMG ?= serviceapp-operator:0.1.0
ENVTEST_K8S_VERSION ?= 1.31.0
GOBIN_DIR := $(shell go env GOPATH)/bin

.PHONY: build vet test test-envtest lint docker-build helm-lint smoke

build:
	go build -o bin/manager .

vet:
	go vet ./...

# Unit tests always run. The envtest tests need the kube-apiserver and etcd
# binaries, which setup-envtest downloads once into a cache folder.
test:
	go test ./...

test-envtest:
	go install sigs.k8s.io/controller-runtime/tools/setup-envtest@release-0.19
	KUBEBUILDER_ASSETS="$$($(GOBIN_DIR)/setup-envtest use -p path $(ENVTEST_K8S_VERSION))" \
	  go test -v -count=1 ./internal/controller/...

lint:
	golangci-lint run ./...

docker-build:
	docker build -t $(IMG) .

helm-lint:
	helm lint chart --strict

# Needs a running kind or k3s cluster with the image loaded and the chart installed.
smoke:
	./test/smoke/smoke.sh
