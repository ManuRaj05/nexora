#!/usr/bin/env bash
set -Eeuo pipefail

# Run on the existing Azure VM as azureuser.
# This script is safe to rerun and does not recreate the VM.

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

echo "==> Checking k3s"
sudo kubectl wait --for=condition=Ready node --all --timeout=120s

echo "==> Installing Helm if missing"
if ! command -v helm >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | sudo bash
fi
helm version

echo "==> Installing Argo CD if missing"
if ! sudo kubectl get namespace argocd >/dev/null 2>&1; then
  sudo kubectl create namespace argocd
fi

if ! sudo kubectl get deployment argocd-server -n argocd >/dev/null 2>&1; then
  sudo kubectl apply -n argocd \
    -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
fi

echo "==> Waiting for Argo CD"
sudo kubectl rollout status deployment/argocd-server -n argocd --timeout=300s
sudo kubectl rollout status deployment/argocd-repo-server -n argocd --timeout=300s

echo "==> Creating Nexora runtime credentials if absent"
if ! sudo kubectl get secret nexora-runtime -n nexora >/dev/null 2>&1; then
  POSTGRES_PASSWORD="$(openssl rand -hex 24)"
  JWT_SECRET="$(openssl rand -hex 32)"
  ORDER_SERVICE_TOKEN="$(openssl rand -hex 32)"

  sudo kubectl create namespace nexora --dry-run=client -o yaml | sudo kubectl apply -f -

  sudo kubectl create secret generic nexora-runtime -n nexora \
    --from-literal=POSTGRES_USER=nexora_admin \
    --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    --from-literal=USER_DATABASE_URL="postgresql://nexora_admin:${POSTGRES_PASSWORD}@postgres:5432/nexora_users" \
    --from-literal=PRODUCT_DATABASE_URL="postgresql://nexora_admin:${POSTGRES_PASSWORD}@postgres:5432/nexora_products" \
    --from-literal=ORDER_DATABASE_URL="postgresql://nexora_admin:${POSTGRES_PASSWORD}@postgres:5432/nexora_orders" \
    --from-literal=JWT_SECRET="$JWT_SECRET" \
    --from-literal=ORDER_SERVICE_TOKEN="$ORDER_SERVICE_TOKEN"
else
  echo "Runtime Secret already exists; keeping existing credentials."
fi

echo "==> Bootstrap prerequisites are ready"
echo "Next: configure the Argo CD Application after the chart is available in GitHub."
