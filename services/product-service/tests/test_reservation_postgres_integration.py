import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import Error as PsycopgError
from fastapi.testclient import TestClient


SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import main as product_service


class ReservationPostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("NEXORA_RUN_DISPOSABLE_PRODUCT_POSTGRES_TESTS") != "1":
            raise unittest.SkipTest("requires explicit disposable PostgreSQL test opt-in")

        cls.database_url = os.getenv("TEST_DATABASE_URL")
        if not cls.database_url:
            raise unittest.SkipTest("TEST_DATABASE_URL is required for disposable PostgreSQL tests")

        conninfo = psycopg.conninfo.conninfo_to_dict(cls.database_url)
        database_name = conninfo.get("dbname", "")
        if database_name in {"nexora_products", "nexora_orders", "nexora_users"} or not database_name.endswith("_test"):
            raise RuntimeError("Refusing integration tests unless TEST_DATABASE_URL targets a disposable *_test database")

        with psycopg.connect(cls.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database();")
                if cursor.fetchone()[0] != database_name:
                    raise RuntimeError("TEST_DATABASE_URL database identity did not match the requested test database")
                cursor.execute("SELECT to_regclass('public.products'), to_regclass('public.stock_reservations'), to_regclass('public.reservation_operations');")
                if cursor.fetchone() != ("products", "stock_reservations", "reservation_operations"):
                    raise RuntimeError("Disposable Product Service schema is not initialized")

        cls.original_get_connection = product_service.get_connection
        product_service.get_connection = lambda: psycopg.connect(cls.database_url)
        cls.client = TestClient(product_service.app)
        cls.service_token = "disposable-integration-test-token"
        cls.token_patch = patch.dict(os.environ, {"ORDER_SERVICE_TOKEN": cls.service_token})
        cls.token_patch.start()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "original_get_connection"):
            product_service.get_connection = cls.original_get_connection
        if hasattr(cls, "client"):
            cls.client.close()
        if hasattr(cls, "token_patch"):
            cls.token_patch.stop()

    def setUp(self):
        self.reservation_ids = set()
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO products (name, description, price, stock, category)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (f"audit-{uuid4()}", "Disposable integration product", 1, 1, "test"),
                )
                self.product_id = cursor.fetchone()[0]

    def tearDown(self):
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                if self.reservation_ids:
                    cursor.execute(
                        "DELETE FROM reservation_operations WHERE reservation_id = ANY(%s);",
                        (list(self.reservation_ids),),
                    )
                    cursor.execute(
                        "DELETE FROM stock_reservations WHERE reservation_id = ANY(%s);",
                        (list(self.reservation_ids),),
                    )
                cursor.execute("DELETE FROM products WHERE id = %s;", (self.product_id,))

    def call_reserve(self, reservation_id, generation=0, quantity=1):
        self.reservation_ids.add(reservation_id)
        return self.client.post(
            f"/products/{self.product_id}/reserve",
            params={
                "quantity": quantity,
                "reservation_id": str(reservation_id),
                "fencing_generation": generation,
            },
            headers={"X-Order-Service-Token": self.service_token},
        )

    def call_release(self, reservation_id, generation=0):
        return self.client.post(
            f"/products/{self.product_id}/release",
            params={
                "quantity": 1,
                "reservation_id": str(reservation_id),
                "fencing_generation": generation,
            },
            headers={"X-Order-Service-Token": self.service_token},
        )

    def test_distinct_concurrent_reservations_cannot_oversell_last_unit(self):
        reservation_ids = [uuid4(), uuid4()]
        barrier = threading.Barrier(2)

        def reserve(reservation_id):
            self.reservation_ids.add(reservation_id)
            with TestClient(product_service.app) as client:
                barrier.wait()
                return client.post(
                    f"/products/{self.product_id}/reserve",
                    params={"quantity": 1, "reservation_id": str(reservation_id)},
                    headers={"X-Order-Service-Token": self.service_token},
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(reserve, reservation_ids))

        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT stock FROM products WHERE id = %s;", (self.product_id,))
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT count(*) FROM stock_reservations WHERE product_id = %s AND status = 'RESERVED';",
                    (self.product_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

    def test_insufficient_stock_does_not_change_stock_or_create_reservation(self):
        reservation_id = uuid4()
        response = self.call_reserve(reservation_id, quantity=2)

        self.assertEqual(response.status_code, 409)
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT stock FROM products WHERE id = %s;", (self.product_id,))
                self.assertEqual(cursor.fetchone()[0], 1)
                cursor.execute(
                    "SELECT count(*) FROM stock_reservations WHERE reservation_id = %s;",
                    (reservation_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT count(*) FROM reservation_operations WHERE reservation_id = %s;",
                    (reservation_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_zero_quantity_and_missing_product_are_rejected_without_changes(self):
        reservation_id = uuid4()
        self.reservation_ids.add(reservation_id)
        invalid_quantity = self.client.post(
            f"/products/{self.product_id}/reserve",
            params={"quantity": 0, "reservation_id": str(reservation_id)},
            headers={"X-Order-Service-Token": self.service_token},
        )
        missing_product = self.client.post(
            "/products/-1/reserve",
            params={"quantity": 1, "reservation_id": str(uuid4())},
            headers={"X-Order-Service-Token": self.service_token},
        )

        self.assertEqual(invalid_quantity.status_code, 400)
        self.assertEqual(missing_product.status_code, 404)
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT stock FROM products WHERE id = %s;", (self.product_id,))
                self.assertEqual(cursor.fetchone()[0], 1)
                cursor.execute(
                    "SELECT count(*) FROM reservation_operations WHERE reservation_id = %s;",
                    (reservation_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_concurrent_reserves_for_same_uuid_decrement_stock_once(self):
        reservation_id = uuid4()
        self.reservation_ids.add(reservation_id)
        barrier = threading.Barrier(2)

        def reserve():
            with TestClient(product_service.app) as client:
                barrier.wait()
                return client.post(
                    f"/products/{self.product_id}/reserve",
                    params={"quantity": 1, "reservation_id": str(reservation_id)},
                    headers={"X-Order-Service-Token": self.service_token},
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: reserve(), range(2)))

        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(sorted(response.json()["already_reserved"] for response in responses), [False, True])
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT stock FROM products WHERE id = %s;", (self.product_id,))
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT count(*) FROM stock_reservations WHERE reservation_id = %s;",
                    (reservation_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

    def test_concurrent_releases_for_same_uuid_change_stock_once(self):
        reservation_id = uuid4()
        first = self.call_reserve(reservation_id)
        self.assertEqual(first.status_code, 200)

        barrier = threading.Barrier(2)

        def release():
            with TestClient(product_service.app) as client:
                barrier.wait()
                return client.post(
                    f"/products/{self.product_id}/release",
                    params={"quantity": 1, "reservation_id": str(reservation_id)},
                    headers={"X-Order-Service-Token": self.service_token},
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: release(), range(2)))

        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual({response.json()["status"] for response in responses}, {"RELEASED"})
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT stock FROM products WHERE id = %s;", (self.product_id,))
                self.assertEqual(cursor.fetchone()[0], 1)
                cursor.execute(
                    "SELECT status FROM stock_reservations WHERE reservation_id = %s;",
                    (reservation_id,),
                )
                self.assertEqual(cursor.fetchone()[0], "RELEASED")

    def test_cancellation_fences_delayed_stale_reserve(self):
        reservation_id = uuid4()
        self.reservation_ids.add(reservation_id)
        cancelled = self.client.post(
            f"/products/{self.product_id}/cancel",
            params={"quantity": 1, "reservation_id": str(reservation_id), "fencing_generation": 1},
            headers={"X-Order-Service-Token": self.service_token},
        )
        delayed_reserve = self.call_reserve(reservation_id, generation=0)

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")
        self.assertEqual(delayed_reserve.status_code, 409)
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT stock FROM products WHERE id = %s;", (self.product_id,))
                self.assertEqual(cursor.fetchone()[0], 1)
                cursor.execute(
                    "SELECT status, fencing_generation FROM reservation_operations WHERE reservation_id = %s;",
                    (reservation_id,),
                )
                self.assertEqual(cursor.fetchone(), ("CANCELLED", 1))

    def test_product_delete_waits_until_active_reservation_is_released(self):
        reservation_id = uuid4()
        self.assertEqual(self.call_reserve(reservation_id).status_code, 200)

        with patch.object(product_service, "require_admin"):
            deletion = self.client.delete(
                f"/products/{self.product_id}",
                headers={"Authorization": "Bearer disposable-admin-token"},
            )
        self.assertEqual(deletion.status_code, 409)

        released = self.call_release(reservation_id)
        self.assertEqual(released.status_code, 200)
        with patch.object(product_service, "require_admin"):
            deletion = self.client.delete(
                f"/products/{self.product_id}",
                headers={"Authorization": "Bearer disposable-admin-token"},
            )
        self.assertEqual(deletion.status_code, 200)

    def test_reservation_insert_failure_rolls_back_stock_decrement(self):
        reservation_id = uuid4()
        self.reservation_ids.add(reservation_id)
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE FUNCTION public.audit_reject_reservation_operation()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                        RAISE EXCEPTION 'intentional disposable-test failure';
                    END;
                    $$;
                    CREATE TRIGGER audit_reject_reservation_operation
                    BEFORE INSERT ON public.reservation_operations
                    FOR EACH ROW EXECUTE FUNCTION public.audit_reject_reservation_operation();
                    """
                )

        try:
            with self.assertRaises(PsycopgError):
                self.call_reserve(reservation_id)
            with psycopg.connect(self.database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT stock FROM products WHERE id = %s;", (self.product_id,))
                    self.assertEqual(cursor.fetchone()[0], 1)
                    cursor.execute(
                        "SELECT count(*) FROM stock_reservations WHERE reservation_id = %s;",
                        (reservation_id,),
                    )
                    self.assertEqual(cursor.fetchone()[0], 0)
        finally:
            with psycopg.connect(self.database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DROP TRIGGER IF EXISTS audit_reject_reservation_operation ON public.reservation_operations;")
                    cursor.execute("DROP FUNCTION IF EXISTS public.audit_reject_reservation_operation();")


if __name__ == "__main__":
    unittest.main()
