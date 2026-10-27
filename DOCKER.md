# Nexora local Docker environment

## Configure and start

1. If a root `.env` does not already exist, copy the template and replace its
   placeholders with local-only values:

   ```sh
   cp -n .env.example .env
   ```

   `POSTGRES_PASSWORD` must use URL-safe characters because Compose inserts it
   into the service connection URLs. Set `JWT_SECRET` and
   `ORDER_SERVICE_TOKEN` to separate, strong random values. The root `.env` is
   ignored by Git.

2. Build and start the environment:

   ```sh
   docker compose up --build -d
   docker compose ps
   ```

3. Browse to <http://localhost:5173>. The API is available at
   <http://localhost:8081> for direct local debugging; the browser frontend
   uses the same-origin `/api` reverse proxy and does not call microservices.

## Services and persistence

Compose runs the React/Nginx frontend, API Gateway, User Service, Product
Service, Order Service, reconciliation worker, and a dedicated PostgreSQL
container on the `nexora-internal` network. Only the frontend and Gateway have
host ports. PostgreSQL and the individual microservices are not published on
host ports.

PostgreSQL creates the three application databases and applies the clean
schemas from `infra/postgres/schema/` (User Service reuses its checked-in
`schema.sql`) on first initialization of the named `nexora-postgres-data`
volume. Initialization stops on SQL errors. `docker compose down` stops the
containers but keeps this data volume. Do not apply the legacy upgrade SQL to
the clean-install databases; see `infra/postgres/README.md`.

`POSTGRES_USER` and `POSTGRES_PASSWORD` only initialize a new data volume.
Changing them in `.env` later does not rotate roles in an existing volume; use
a deliberate database role-rotation procedure if those credentials change.

To stop the local environment while retaining database contents:

```sh
docker compose down
```

## Local application commands

The containerized frontend uses Nginx and `/api`. Running Vite directly still
uses the existing `VITE_API_BASE_URL` setting and its local Gateway fallback.
The backend services continue to support their existing local commands, for
example `uvicorn main:app --reload --port 8000` from a service directory. Their
service `.env.example` files show local host URL values; Compose injects the
container DNS names instead.

To provision the first administrator after registering that account, use the
existing guarded CLI inside the User Service container and complete its
interactive confirmation:

```sh
docker compose exec -it user-service python provision_admin.py ACCOUNT_EMAIL
```

Never use the Compose placeholders as production credentials.
