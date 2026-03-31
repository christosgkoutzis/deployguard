#!/bin/bash
set -e

echo "INFO: Bootstrapping ArgoCD Platform..."

helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

echo "INFO: Creating namespace and installing ArgoCD..."
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -


helm upgrade --install argocd argo/argo-cd \
    --namespace argocd \
    --set server.service.type=ClusterIP \
    --wait

echo "INFO: ArgoCD is installed and pods are ready!"