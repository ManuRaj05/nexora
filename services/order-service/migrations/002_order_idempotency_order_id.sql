BEGIN;

ALTER TABLE order_idempotency
    ADD COLUMN order_id BIGINT,
    ADD CONSTRAINT order_idempotency_order_id_fkey
        FOREIGN KEY (order_id) REFERENCES orders(id);

COMMIT;
