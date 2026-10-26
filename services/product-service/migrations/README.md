# Product Service migrations

`001_reservation_operations.sql` is transactional and records its version in
`product_service_schema_migrations`. Apply it once with a PostgreSQL client that
stops on the first error. Do not bypass the version table or rerun a partially
edited migration. A recorded version with a missing table, required column, or
constraint raises an exception; an existing unrecorded ledger causes the create
step to fail and the transaction to roll back. The migration also checks the
backfilled ledger against `stock_reservations` before recording success.

After application, verify the recorded version:

```sql
SELECT version, applied_at
FROM product_service_schema_migrations
WHERE version = '001_reservation_operations';
```

Expect exactly one row. Verify column names, types, and nullability:

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND table_name = 'reservation_operations'
ORDER BY ordinal_position;
```

Expect `reservation_id uuid`, `product_id integer`, `quantity integer`,
`fencing_generation bigint`, `status text`, `created_at timestamp with time zone`,
and `updated_at timestamp with time zone`; all are `NOT NULL`.

Verify the primary key and checks:

```sql
SELECT c.contype, pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint AS c
WHERE c.conrelid = 'reservation_operations'::regclass
ORDER BY c.contype, c.conname;
```

Expect a primary key on `reservation_id`, and checks enforcing `quantity > 0`,
`fencing_generation >= 0`, and status membership in `RESERVED`, `RELEASED`, or
`CANCELLED`. Any missing or different result means the schema is inconsistent;
stop deployment and investigate rather than editing the live schema manually.
