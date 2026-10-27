# Nexora Helm deployment for local kind

This chart deploys the existing Nexora application into the local kind cluster. It does not interact with the Docker Compose database or the host PostgreSQL installation.

## Architecture

The chart includes a PostgreSQL Deployment with its own `nexora-k8s-postgres-data` PVC, User/Product/Order Services, API Gateway, frontend, and the order reconciliation worker. Backend Services and PostgreSQL are ClusterIP-only. Service DNS names match the current Compose names (`postgres`, `user-service`, `product-service`, `order-service`, and `api-gateway`). The frontend image's Nginx configuration sends browser `/api/...` requests to `http://api-gateway:8081/`; the browser therefore only needs access to the frontend.

Kubernetes init containers wait for PostgreSQL and required service health endpoints before starting dependent workloads. The worker has no HTTP endpoint and intentionally has no HTTP probes; Kubernetes restarts it if its process exits. The other workloads use the health routes already present in their images.

PostgreSQL initialization mounts the checked-in clean-install scripts and schemas into `/docker-entrypoint-initdb.d` and `/schema`. PostgreSQL runs these scripts only when the PVC is empty. They create `nexora_users`, `nexora_products`, and `nexora_orders` and apply the final clean-install schema. The chart does not run upgrade migrations. Do not point this chart at a Compose or host database.

The SQL/init files are copied into `deploy/helm/nexora/files/postgres/` because Helm packages chart-local files only. When those source files change, update the chart copies and compare them before releasing.

## Prepare local kind

Use the specified context and load each already-built local image into the existing kind cluster:

```sh
kind load docker-image --name nexora \
  nexora-frontend:latest \
  nexora-api-gateway:latest \
  nexora-user-service:latest \
  nexora-product-service:latest \
  nexora-order-service:latest \
  nexora-order-reconciliation-worker:latest \
  postgres:17.11-alpine3.24
```

Create the target namespace, then create/update the Kubernetes Secret from the ignored root `.env` without printing its contents:

```sh
kubectl --context kind-nexora create namespace nexora --dry-run=client -o yaml | kubectl --context kind-nexora apply -f -
bash deploy/helm/create-secret.sh
```

The helper reads `POSTGRES_USER`, `POSTGRES_PASSWORD`, `JWT_SECRET`, and `ORDER_SERVICE_TOKEN` from `.env`. It creates the three Kubernetes-internal database URLs with the `postgres` Service hostname, writes a mode-0600 temporary env file, passes that file directly to `kubectl`, and removes it on exit. The command requires an existing root `.env`; do not copy `.env` contents into Helm values or commit them. The Kubernetes Secret is named `nexora-runtime` in namespace `nexora`, matching chart defaults.

The clean database starts with no user accounts, and the chart does not seed an administrator. Register the initial account through the application, then use the existing interactive provisioning tool from the User Service container:

```sh
kubectl --context kind-nexora -n nexora exec -it deployment/nexora-user-service -- \
  python provision_admin.py you@example.test
```

The tool asks for an interactive confirmation and refuses to promote an account if an administrator already exists.

## Install and access

The following are instructions for a later deployment; they have not been run as part of chart preparation:

```sh
helm upgrade --install nexora deploy/helm/nexora \
  --kube-context kind-nexora --namespace nexora
kubectl --context kind-nexora -n nexora port-forward service/frontend 5173:8080
```

Open <http://localhost:5173>. The API Gateway remains internal; the frontend Nginx proxy routes `/api` to it over cluster DNS. For local administration/debugging only, a separate port-forward can expose the gateway:

```sh
kubectl --context kind-nexora -n nexora port-forward service/api-gateway 8081:8081
```

## Inspect workloads

```sh
kubectl --context kind-nexora -n nexora get pods,services,pvc
kubectl --context kind-nexora -n nexora get events --sort-by=.lastTimestamp
kubectl --context kind-nexora -n nexora logs deployment/nexora-user-service
kubectl --context kind-nexora -n nexora logs deployment/nexora-product-service
kubectl --context kind-nexora -n nexora logs deployment/nexora-order-service
kubectl --context kind-nexora -n nexora logs deployment/nexora-api-gateway
kubectl --context kind-nexora -n nexora logs deployment/nexora-frontend
kubectl --context kind-nexora -n nexora logs deployment/nexora-order-reconciliation-worker
kubectl --context kind-nexora -n nexora logs deployment/nexora-postgres
```

Avoid dumping Secret objects or command output that contains credentials into shared logs.

## Uninstall and storage

```sh
helm uninstall nexora --kube-context kind-nexora --namespace nexora
```

The PVC has Helm's `keep` policy, so uninstall preserves the Kubernetes database volume and its data. The retained `nexora-k8s-postgres-data` claim is separate from Compose's `nexora-postgres-data` volume. Do not delete the PVC unless intentionally discarding the Kubernetes data; removing the claim can make its backing storage eligible for deletion depending on the cluster's storage reclaim policy.

## Difference from Compose

Compose uses a bridge network, host port mappings, `depends_on`, and the `nexora-postgres-data` Docker volume. This chart uses Kubernetes ClusterIP Services/DNS, init containers and probes instead of `depends_on`, a separate PVC, and `kubectl port-forward` for local browser access. Both environments initialize the same clean-install schemas but have separate databases and persistent storage. The chart currently targets one local kind cluster and uses `imagePullPolicy: Never`; it is not a production deployment or a registry-based release process.
