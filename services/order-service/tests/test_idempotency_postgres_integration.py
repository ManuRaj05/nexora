import hashlib
import json
import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
import psycopg
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb


SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import main as order_service


class IdempotencyPostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("NEXORA_RUN_DISPOSABLE_ORDER_POSTGRES_TESTS") != "1":
            raise unittest.SkipTest("requires explicit disposable PostgreSQL test opt-in")

        cls.database_url = os.getenv("TEST_DATABASE_URL")
        if not cls.database_url:
            raise unittest.SkipTest("TEST_DATABASE_URL is required for disposable PostgreSQL tests")

        database_name = psycopg.conninfo.conninfo_to_dict(cls.database_url).get("dbname", "")
        if database_name in {"nexora_products", "nexora_orders", "nexora_users"} or not database_name.endswith("_test"):
            raise RuntimeError("Refusing integration tests unless TEST_DATABASE_URL targets a disposable *_test database")

        with psycopg.connect(cls.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), to_regclass('public.order_idempotency');")
                if cursor.fetchone() != (database_name, "order_idempotency"):
                    raise RuntimeError("Disposable Order Service schema is not initialized")

        cls.original_get_connection = order_service.get_connection
        order_service.get_connection = lambda: psycopg.connect(cls.database_url)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "original_get_connection"):
            order_service.get_connection = cls.original_get_connection

    def setUp(self):
        self.user_id = uuid4().int % 2_000_000_000 + 1
        self.key_digest = hashlib.sha256(uuid4().bytes).digest()
        self.request_digest = hashlib.sha256(uuid4().bytes).digest()
        self.payload = {"user_id": self.user_id, "items": [{"product_id": 17, "quantity": 1}]}
        self.order_ids = []
        self.reservations = [{
            "reservation_id": str(uuid4()),
            "product_id": 17,
            "quantity": 1,
            "state": "NOT_STARTED",
        }]

    def tearDown(self):
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM order_idempotency WHERE user_id = %s;", (self.user_id,))
                cursor.execute("DELETE FROM orders WHERE user_id = %s;", (self.user_id,))

    def claim(self, request_digest=None):
        return order_service.create_idempotency_record(
            self.user_id,
            self.key_digest,
            request_digest or self.request_digest,
            self.payload,
            self.reservations,
        )

    def test_concurrent_same_key_claims_create_one_postgres_record(self):
        barrier = threading.Barrier(2)

        def claim():
            barrier.wait()
            try:
                return self.claim()
            except HTTPException as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))

        created = [result for result in results if isinstance(result, tuple)]
        conflicts = [result for result in results if isinstance(result, HTTPException)]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].status_code, 409)
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM order_idempotency WHERE user_id = %s AND key_digest = %s;",
                    (self.user_id, self.key_digest),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

    def test_key_payload_mismatch_conflicts_and_completed_result_replays(self):
        idempotency_id, _, _ = self.claim()
        with self.assertRaises(HTTPException) as mismatch:
            self.claim(request_digest=hashlib.sha256(uuid4().bytes).digest())
        self.assertEqual(mismatch.exception.status_code, 409)

        response_body = {"id": 991, "user_id": self.user_id, "status": "PENDING", "items": []}
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE order_idempotency
                    SET state = 'COMPLETED', response_status = 200,
                        response_body = %s, order_id = NULL
                    WHERE id = %s;
                    """,
                    (Jsonb(response_body), idempotency_id),
                )

        _, _, replay = self.claim()
        self.assertIsInstance(replay, JSONResponse)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(json.loads(replay.body), response_body)

    def test_checkout_persists_exact_decimal_amount_and_replay_has_one_order(self):
        order = order_service.OrderCreate(
            user_id=self.user_id,
            items=[
                order_service.OrderItemCreate(product_id=17, quantity=1),
                order_service.OrderItemCreate(product_id=18, quantity=1),
            ],
        )
        request = Mock(headers={
            "Idempotency-Key": "disposable-decimal-checkout-key",
            "Authorization": "Bearer disposable-test-token",
        })
        get_responses = [
            httpx.Response(200, json=[self.user_id, "test-customer"]),
            httpx.Response(200, json=[17, "Product A", "", 0.1, 5, "test"]),
            httpx.Response(200, json=[18, "Product B", "", 0.2, 5, "test"]),
        ]

        def reserve(url, params=None, **kwargs):
            product_id = 17 if url.endswith("/17/reserve") else 18
            return httpx.Response(200, json={
                "reservation_id": params["reservation_id"],
                "product_id": product_id,
            })

        with patch.dict(os.environ, {"ORDER_SERVICE_TOKEN": "disposable-test-service-token"}), \
             patch.object(order_service.httpx, "get", side_effect=get_responses), \
             patch.object(order_service.httpx, "post", side_effect=reserve) as reserve_request:
            result = order_service.create_order(order, request, {"user_id": self.user_id})
            self.order_ids.append(result["id"])
            replay = order_service.create_order(order, request, {"user_id": self.user_id})

        self.assertEqual(result["total_amount"], 0.3)
        self.assertEqual([item["price"] for item in result["items"]], [0.1, 0.2])
        self.assertIsInstance(replay, JSONResponse)
        self.assertEqual(json.loads(replay.body), result)
        self.assertEqual(reserve_request.call_count, 2)
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT total_amount FROM orders WHERE id = %s;", (result["id"],))
                self.assertEqual(cursor.fetchone()[0], Decimal("0.30"))
                cursor.execute(
                    "SELECT price FROM order_items WHERE order_id = %s ORDER BY product_id;",
                    (result["id"],),
                )
                self.assertEqual([row[0] for row in cursor.fetchall()], [Decimal("0.10"), Decimal("0.20")])
                cursor.execute(
                    "SELECT state, order_id FROM order_idempotency WHERE user_id = %s;",
                    (self.user_id,),
                )
                self.assertEqual(cursor.fetchone(), ("COMPLETED", result["id"]))


if __name__ == "__main__":
    unittest.main()
