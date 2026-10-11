# Stack efímero exp2-eda. NADA de esto se ejecuta solo: invoca cada target a propósito.
# `up` y `down` crean/destruyen recursos con costo (~0,28 USD/h). Destruye siempre al terminar.
SHELL := /bin/bash
# Ejecutar `make` desde este directorio (la ruta puede contener espacios: todo va entre comillas).
HERE  := $(CURDIR)
ROOT  := $(CURDIR)/../../..
REGION ?= us-east-1
CLUSTER_NAME ?= voltera-exp2-eph

.PHONY: help fmt validate up cluster platform kubeconfig relay-bootstrap down status

help:
	@echo "targets: fmt validate up down status relay-bootstrap (up/down tienen costo)"

fmt:
	terraform -chdir="$(HERE)/cluster" fmt -recursive
	terraform -chdir="$(HERE)/platform" fmt -recursive

# Solo lectura/local: no toca AWS ni el clúster.
validate:
	@for d in cluster platform; do \
	  echo "== $$d"; \
	  terraform -chdir="$(HERE)/$$d" fmt -check -recursive && \
	  terraform -chdir="$(HERE)/$$d" init -backend=false -input=false >/dev/null && \
	  terraform -chdir="$(HERE)/$$d" validate || exit 1; \
	done

# CREA recursos con costo. Requiere el stack base aplicado (estado local).
up: cluster kubeconfig platform
	@echo "Listo. Para el relay: make relay-bootstrap  (y aplicar los cambios de base descritos en el README)."
	@echo "RECUERDA: make down al terminar."

cluster:
	terraform -chdir="$(HERE)/cluster" init -input=false
	terraform -chdir="$(HERE)/cluster" apply

kubeconfig:
	aws eks update-kubeconfig --region $(REGION) --name $(CLUSTER_NAME)

platform:
	terraform -chdir="$(HERE)/platform" init -input=false
	terraform -chdir="$(HERE)/platform" apply

relay-bootstrap:
	@"$(ROOT)/scripts/kafka-relay-bootstrap.sh"

down:
	"$(ROOT)/scripts/destroy-ephemeral.sh"

status:
	-kubectl get nodes
	-kubectl -n kafka get kafka,kafkanodepool,kafkatopic,kafkamirrormaker2,pods,pvc
	-kubectl -n voltera get deploy,pods,scaledobject,hpa
	-aws eks describe-cluster --region $(REGION) --name $(CLUSTER_NAME) --query 'cluster.[status,version]' --output text
