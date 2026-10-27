# Local PostgreSQL initialization

Compose initializes a fresh named volume through the scripts in `init/`.
`01-create-databases.sh` creates `nexora_users`, `nexora_products`, and
`nexora_orders`; `02-apply-schemas.sh` applies the clean-install SQL to each
database using `psql` with `ON_ERROR_STOP`. An SQL error stops initialization.
The host PostgreSQL installation is not used or changed.

The User Service schema is `services/user-service/schema.sql`. It is for a new
database; `services/user-service/migrations/001_user_roles.sql` is only for a
legacy User Service database and must not be run after clean initialization.

The Product Service baseline includes its products and reservation tables,
the fencing ledger, and migration version `001_reservation_operations`.
The checked-in Product Service migration validates that recorded final schema;
do not apply it to this initialized database as an upgrade.

The Order Service baseline includes orders, items, idempotency, and
reconciliation tables. It incorporates changes from migrations 001 and 002
and records both baseline versions in `order_service_schema_migrations` for
documentation. Those SQL migration files are for an older database and must
not be run against a database initialized from this baseline. There is no
Order Service migration runner in the application.

The clean-install SQL for Product and Order Service is based on current source
queries and migrations because no base-table DDL for those services is checked
into the repository. It intentionally does not add cross-database foreign
keys. Order item `product_id` is not a foreign key, so deleting a product
cannot erase or block historical order items.
