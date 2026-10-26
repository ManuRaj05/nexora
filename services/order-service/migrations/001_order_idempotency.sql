BEGIN;

CREATE TABLE order_idempotency (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL CHECK (user_id > 0),
    key_digest BYTEA NOT NULL
        CHECK (octet_length(key_digest) = 32),
    request_digest BYTEA NOT NULL
        CHECK (octet_length(request_digest) = 32),
    request_payload JSONB NOT NULL
        CHECK (jsonb_typeof(request_payload) = 'object'),
    reservation_ids JSONB NOT NULL
        CHECK (jsonb_typeof(reservation_ids) = 'array'),
    state TEXT NOT NULL
        CHECK (state IN (
            'IN_PROGRESS',
            'RECOVERY_REQUIRED',
            'COMPLETED',
            'FAILED'
        )),
    response_status SMALLINT,
    response_body JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT order_idempotency_user_key_unique
        UNIQUE (user_id, key_digest),

    CONSTRAINT order_idempotency_response_state_check
        CHECK (
            (
                state IN ('COMPLETED', 'FAILED')
                AND response_status IS NOT NULL
                AND response_status BETWEEN 100 AND 599
                AND response_body IS NOT NULL
                AND jsonb_typeof(response_body) = 'object'
            )
            OR
            (
                state IN ('IN_PROGRESS', 'RECOVERY_REQUIRED')
                AND response_status IS NULL
                AND response_body IS NULL
            )
        )
);

CREATE INDEX order_idempotency_pending_recovery_idx
    ON order_idempotency (updated_at)
    WHERE state IN ('IN_PROGRESS', 'RECOVERY_REQUIRED');

COMMIT;
