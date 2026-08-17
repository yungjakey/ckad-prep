#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CKAD_CLUSTER_NAME:-ckad-prep}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

log()  { printf "\033[1;32m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33mWARN:\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31mERR:\033[0m %s\n" "$*" >&2; }

# --- prereqs ---
for cmd in kind kubectl helm; do
  command -v "$cmd" >/dev/null 2>&1 || { err "$cmd not found. Install it first."; exit 1; }
done

# --- cluster ---
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  warn "Cluster '${CLUSTER_NAME}' already exists. Skipping creation."
else
  log "Creating kind cluster '${CLUSTER_NAME}'..."
  kind create cluster --config "${SCRIPT_DIR}/cluster.yaml" --name "$CLUSTER_NAME" --wait 120s
fi

# point kubectl at the cluster
kubectl cluster-info --context "kind-${CLUSTER_NAME}" >/dev/null 2>&1

log "Waiting for nodes to be ready..."
kubectl wait --for=condition=Ready node --all --timeout=120s

# --- label nodes for CKAD exercise naming ---
# kind names nodes <cluster>-control-plane and <cluster>-worker
# CKAD exercises reference 'controlplane' and 'node01'
WORKER=$(kubectl get nodes -l '!node-role.kubernetes.io/control-plane' -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$WORKER" ]; then
  kubectl label "$WORKER" kubernetes.io/hostname=node01 --overwrite 2>/dev/null || true
  log "Labeled worker as node01"
fi

# --- metrics-server (for kubectl top) ---
if kubectl top nodes >/dev/null 2>&1; then
  log "Metrics-server already running."
else
  log "Installing metrics-server via helm..."
  helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ 2>/dev/null || true
  helm repo update metrics-server
  helm upgrade --install metrics-server metrics-server/metrics-server \
    --namespace kube-system \
    --set args='{--kubelet-insecure-tls}' \
    --wait
fi

# --- ingress-nginx (for ingress exercises) ---
if kubectl get ns ingress-nginx >/dev/null 2>&1; then
  log "ingress-nginx already installed."
else
  log "Installing ingress-nginx via helm..."
  helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx 2>/dev/null || true
  helm repo update ingress-nginx
  helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
    --namespace ingress-nginx --create-namespace \
    --set controller.hostPort.enabled=true \
    --set controller.service.type=NodePort \
    --wait
fi

# --- helm repos for helm exercises ---
log "Adding common helm repos..."
helm repo add bitnami https://charts.bitnami.com/bitnami 2>/dev/null || true
helm repo update bitnami

# --- pre-pull images ---
log "Pre-pulling commonly used images..."
for img in nginx:latest busybox:latest busybox:1.28 perl:5.34; do
  kind pull-image "$img" --name "$CLUSTER_NAME" 2>/dev/null || true
done

log "Setup complete. Cluster '${CLUSTER_NAME}' is ready."
log "Context: kind-${CLUSTER_NAME}"
kubectl get nodes -o wide
