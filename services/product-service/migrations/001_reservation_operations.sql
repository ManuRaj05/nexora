BEGIN;

CREATE TABLE IF NOT EXISTS product_service_schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

SELECT pg_advisory_xact_lock(hashtextextended('product-service-schema-migrations', 0));

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM product_service_schema_migrations
        WHERE version = '001_reservation_operations'
    ) THEN
        IF to_regclass('reservation_operations') IS NULL THEN
            RAISE EXCEPTION 'Migration 001 is recorded but reservation_operations is missing';
        END IF;
        IF EXISTS (
            SELECT expected.column_name
            FROM (VALUES
                ('reservation_id', 'uuid', TRUE),
                ('product_id', 'integer', TRUE),
                ('quantity', 'integer', TRUE),
                ('fencing_generation', 'bigint', TRUE),
                ('status', 'text', TRUE),
                ('created_at', 'timestamp with time zone', TRUE),
                ('updated_at', 'timestamp with time zone', TRUE)
            ) AS expected(column_name, data_type, is_required)
            LEFT JOIN information_schema.columns actual
                ON actual.table_schema = current_schema()
               AND actual.table_name = 'reservation_operations'
               AND actual.column_name = expected.column_name
            WHERE actual.column_name IS NULL
               OR actual.data_type <> expected.data_type
               OR (expected.is_required AND actual.is_nullable <> 'NO')
        ) THEN
            RAISE EXCEPTION 'Recorded migration 001 has missing or incompatible columns';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.oid = to_regclass('reservation_operations')
              AND c.contype = 'p'
              AND pg_get_constraintdef(c.oid) = 'PRIMARY KEY (reservation_id)'
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            WHERE c.conrelid = to_regclass('reservation_operations')
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) LIKE '%quantity > 0%'
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            WHERE c.conrelid = to_regclass('reservation_operations')
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) LIKE '%fencing_generation >= 0%'
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            WHERE c.conrelid = to_regclass('reservation_operations')
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) LIKE '%RESERVED%RELEASED%CANCELLED%'
        ) THEN
            RAISE EXCEPTION 'Recorded migration 001 has missing or incompatible constraints';
        END IF;
    ELSE
        IF EXISTS (
            SELECT 1
            FROM stock_reservations
            WHERE status IS NULL OR status NOT IN ('RESERVED', 'RELEASED')
        ) THEN
            RAISE EXCEPTION 'Unexpected stock_reservations status; refusing to backfill';
        END IF;

        CREATE TABLE reservation_operations (
            reservation_id UUID PRIMARY KEY,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            fencing_generation BIGINT NOT NULL CHECK (fencing_generation >= 0),
            status TEXT NOT NULL
                CHECK (status IN ('RESERVED', 'RELEASED', 'CANCELLED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO reservation_operations
            (reservation_id, product_id, quantity, fencing_generation, status, created_at)
        SELECT reservation_id, product_id, quantity, 0, status,
               COALESCE(created_at, CURRENT_TIMESTAMP)
        FROM stock_reservations
        ON CONFLICT (reservation_id) DO NOTHING;

        IF EXISTS (
            SELECT 1
            FROM stock_reservations r
            LEFT JOIN reservation_operations o USING (reservation_id)
            WHERE o.reservation_id IS NULL
               OR o.product_id <> r.product_id
               OR o.quantity <> r.quantity
               OR o.status <> r.status
        ) THEN
            RAISE EXCEPTION 'Reservation backfill is inconsistent; rolling back migration';
        END IF;

        INSERT INTO product_service_schema_migrations (version)
        VALUES ('001_reservation_operations');
    END IF;

    IF EXISTS (
        SELECT 1
        FROM reservation_operations o
        LEFT JOIN stock_reservations r USING (reservation_id)
        WHERE (o.status = 'CANCELLED' AND r.reservation_id IS NOT NULL)
           OR (o.status IN ('RESERVED', 'RELEASED') AND (
               r.reservation_id IS NULL
               OR r.product_id <> o.product_id
               OR r.quantity <> o.quantity
               OR r.status <> o.status
           ))
    ) THEN
        RAISE EXCEPTION 'Reservation ledger disagrees with stock_reservations';
    END IF;
END;
$$;

COMMIT;
