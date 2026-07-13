#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "INFO: Bootstrapping ArgoCD Platform..."

helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

echo "INFO: Creating namespaces..."
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace deployguard --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

echo "INFO: Installing/Upgrading ArgoCD..."
helm upgrade --install argocd argo/argo-cd \
    --namespace argocd \
    --set server.service.type=ClusterIP \
    --set server.ingress.enabled=true \
    --set server.ingress.ingressClassName=traefik \
    --set "server.ingress.hosts[0]=argocd.127.0.0.1.nip.io" \
    --set configs.params."server\.insecure"=true \
    --wait

echo "INFO: Applying ArgoCD application manifests..."
kubectl apply -f "${REPO_ROOT}/platform/gitops"

echo "INFO: ArgoCD is installed and application definitions are ready!"