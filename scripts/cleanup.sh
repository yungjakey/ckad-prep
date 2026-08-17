#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CKAD_CLUSTER_NAME:-ckad-prep}"

log()  { printf "\033[1;32m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33mWARN:\033[0m %s\n" "$*"; }

# Clean up any session-labeled namespaces first
log "Cleaning up session namespaces..."
kubectl get ns -l ckad-session -o name 2>/dev/null | while read -r ns; do
  kubectl delete "$ns" --wait=false 2>/dev/null || true
done

# Delete the kind cluster
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  log "Deleting kind cluster '${CLUSTER_NAME}'..."
  kind delete cluster --name "$CLUSTER_NAME"
  log "Cluster deleted."
else
  warn "Cluster '${CLUSTER_NAME}' not found. Nothing to clean up."
fi
