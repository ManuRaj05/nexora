BEGIN;

-- Upgrade only invalid/unset legacy values. Preserve valid ADMIN assignments;
-- rerunning this upgrade must never demote an administrator.
UPDATE users
SET role = 'CUSTOMER'
WHERE role IS NULL OR role NOT IN ('CUSTOMER', 'ADMIN');

ALTER TABLE users
    ALTER COLUMN role SET DEFAULT 'CUSTOMER',
    ALTER COLUMN role SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'users'::regclass
          AND conname IN ('users_role_check', 'users_role_allowed_check')
          AND contype = 'c'
          AND convalidated
          AND pg_get_constraintdef(oid) LIKE '%role%CUSTOMER%ADMIN%'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_role_check
            CHECK (role IN ('CUSTOMER', 'ADMIN'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'users'::regclass
          AND conname IN ('users_role_check', 'users_role_allowed_check')
          AND contype = 'c'
          AND convalidated
          AND pg_get_constraintdef(oid) LIKE '%role%CUSTOMER%ADMIN%'
    ) THEN
        RAISE EXCEPTION 'users_role_allowed_check is missing or incompatible';
    END IF;
END;
$$;

COMMIT;
