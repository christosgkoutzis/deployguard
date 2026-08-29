#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  source "${REPO_ROOT}/.env"
  set +a
else
  echo "ERROR: .env file not found! Please create it based on .env.example before bootstrapping."
  exit 1
fi

echo "INFO: Bootstrapping Platform (ArgoCD + External Secrets Operator)..."

helm repo add argo https://argoproj.github.io/argo-helm
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

echo "INFO: Creating namespaces..."
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace deployguard --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace external-secrets --dry-run=client -o yaml | kubectl apply -f -

echo "INFO: Installing/Upgrading ArgoCD..."
helm upgrade --install argocd argo/argo-cd \
    --namespace argocd \
    --set server.service.type=ClusterIP \
    --set server.ingress.enabled=true \
    --set server.ingress.ingressClassName=traefik \
    --set "server.ingress.hosts[0]=argocd.${CLUSTER_DOMAIN}" \
    --set configs.params."server\.insecure"=true \
    --wait \
    --timeout 5m

echo "INFO: Installing/Upgrading External Secrets Operator..."
helm upgrade --install external-secrets external-secrets/external-secrets \
    -n external-secrets \
    --set installCRDs=true \
    --wait \
    --timeout 5m

echo "INFO: Configuring Vault Token for ESO..."
kubectl -n deployguard create secret generic vault-token \
    --from-literal=token="${VAULT_ROOT_TOKEN}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "INFO: Creating Platform Bootstrap Secrets for initial seeding..."
kubectl -n deployguard create secret generic platform-bootstrap-secrets \
    --from-literal=VAULT_ROOT_TOKEN="${VAULT_ROOT_TOKEN}" \
    --from-literal=POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}" \
    --from-literal=MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minio123}" \
    --from-literal=RABBITMQ_PASSWORD="${RABBITMQ_PASSWORD:-guest}" \
    --from-literal=REDIS_PASSWORD="${REDIS_PASSWORD:-redis123}" \
    --from-literal=ELASTIC_PASSWORD="${ELASTIC_PASSWORD:-elastic123}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "INFO: Platform Bootstrapped!"
