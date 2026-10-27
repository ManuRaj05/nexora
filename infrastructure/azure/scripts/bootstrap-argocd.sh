#!/usr/bin/env bash
set -Eeuo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
K=(sudo kubectl)

echo "==> Checking k3s"
"${K[@]}" wait --for=condition=Ready node --all --timeout=120s

echo "==> Installing Helm if missing"
if ! command -v helm >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | sudo bash
fi
helm version

echo "==> Creating application namespace"
"${K[@]}" create namespace nexora \
  --dry-run=client -o yaml | "${K[@]}" apply -f -

echo "==> Installing Argo CD if missing"
"${K[@]}" create namespace argocd \
  --dry-run=client -o yaml | "${K[@]}" apply -f -

if ! "${K[@]}" get deployment argocd-server -n argocd >/dev/null 2>&1; then
  "${K[@]}" apply -n argocd \
    -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
fi

echo "==> Waiting for Argo CD"
"${K[@]}" rollout status deployment/argocd-server -n argocd --timeout=300s
"${K[@]}" rollout status deployment/argocd-repo-server -n argocd --timeout=300s

echo "==> Creating runtime Secret if absent"
if ! "${K[@]}" get secret nexora-runtime -n nexora >/dev/null 2>&1; then
  POSTGRES_PASSWORD="$(openssl rand -hex 24)"
  JWT_SECRET="$(openssl rand -hex 32)"
  ORDER_SERVICE_TOKEN="$(openssl rand -hex 32)"

  "${K[@]}" create secret generic nexora-runtime -n nexora \
    --from-literal=POSTGRES_USER=nexora_admin \
    --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    --from-literal=USER_DATABASE_URL="postgresql://nexora_admin:${POSTGRES_PASSWORD}@postgres:5432/nexora_users" \
    --from-literal=PRODUCT_DATABASE_URL="postgresql://nexora_admin:${POSTGRES_PASSWORD}@postgres:5432/nexora_products" \
    --from-literal=ORDER_DATABASE_URL="postgresql://nexora_admin:${POSTGRES_PASSWORD}@postgres:5432/nexora_orders" \
    --from-literal=JWT_SECRET="$JWT_SECRET" \
    --from-literal=ORDER_SERVICE_TOKEN="$ORDER_SERVICE_TOKEN"
else
  echo "Existing runtime Secret preserved."
fi

echo "==> Registering Nexora with Argo CD"
"${K[@]}" apply -n argocd \
  -f https://raw.githubusercontent.com/ManuRaj05/nexora/main/infrastructure/azure/argocd-application.yaml

echo "==> Bootstrap complete"
echo "Check status with: sudo kubectl get applications -n argocd"
