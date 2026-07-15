#!/usr/bin/env bash
set -euo pipefail

echo "INFO: Starting control plane setup..."

# Checks if a command exists
is_installed() {
    command -v "$1" &> /dev/null
}

install_kubectl() {
    if is_installed "kubectl"; then
        echo "INFO: kubectl is already installed."
        return
    fi
    echo "INFO: Installing kubectl..."
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
    rm kubectl
}

install_k3d() {
    if is_installed "k3d"; then
        echo "INFO: k3d is already installed."
        return
    fi
    echo "INFO: Installing k3d..."
    curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | TAG=v5.6.0 bash
}

install_helm() {
    if is_installed "helm"; then
        echo "INFO: helm is already installed."
        return
    fi
    echo "INFO: Installing helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
}

install_yq() {
    if is_installed "yq"; then
        echo "INFO: yq is already installed."
        return
    fi
    echo "INFO: Installing yq..."
    curl -L "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64" -o /usr/local/bin/yq
    sudo chmod +x /usr/local/bin/yq
}

# Install dependencies
install_dependencies() {
    install_kubectl
    install_k3d
    install_helm
    install_yq
}
install_dependencies

# Cluster setup: Creates a K3d cluster if it doesn't already exist
CLUSTER_NAME="control-plane-cluster"
if k3d cluster list | grep -q "$CLUSTER_NAME"; then
    echo "INFO: Cluster '$CLUSTER_NAME' already exists."
else
    echo "INFO: Creating K3d Cluster: $CLUSTER_NAME..."
    k3d cluster create "${CLUSTER_NAME}" \
      --servers 1 \
      --agents 2 \
      -p "8080:80@loadbalancer" \
      --api-port 6443 \
      --wait
fi