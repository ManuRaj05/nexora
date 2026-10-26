import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException


SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import main as order_service
import reconciliation_worker


SERVICE_TOKEN = "test-only-service-credential"
EXPECTED_HEADERS = {"X-Order-Service-Token": SERVICE_TOKEN}


class FakeResponse:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self.body = body
        self.text = text

    def json(self):
        return self.body


class FakeCursor:
    rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        return (987, 7, 12.5, "PENDING", None)


class FakeConnection:
    def __init__(self):
        self.fake_cursor = FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self):
        return self.fake_cursor


class ProductServiceAuthTests(unittest.TestCase):
    def setUp(self):
        self.token_patch = patch.dict(os.environ, {"ORDER_SERVICE_TOKEN": SERVICE_TOKEN})
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)

    def test_order_reserve_call_sends_internal_token(self):
        records = [{
            "reservation_id": "stable-reservation",
            "product_id": 41,
            "quantity": 1,
            "state": "NOT_STARTED",
        }]
        operation_state = {"tracking_failed": False, "reservation_records": records}
        user_response = FakeResponse(200, [7, "customer"])
        product_response = FakeResponse(200, [41, "Test", "Description", 12.5, 5, "Test"])
        reserve_response = FakeResponse(200, {
            "reservation_id": "stable-reservation",
            "product_id": 41,
        })

        def set_state(idempotency_id, reservation_records, index, state, state_info):
            reservation_records[index]["state"] = state

        with patch.object(order_service, "set_reservation_state", side_effect=set_state), \
             patch.object(order_service, "get_connection", return_value=FakeConnection()), \
             patch.object(order_service.httpx, "get", side_effect=[user_response, product_response]), \
             patch.object(order_service.httpx, "post", return_value=reserve_response) as post:
            result = order_service._process_order(
                order_service.OrderCreate(
                    user_id=7,
                    items=[order_service.OrderItemCreate(product_id=41, quantity=1)],
                ),
                {"user_id": 7},
                records,
                31,
                operation_state,
            )

        self.assertEqual(result["id"], 987)
        self.assertEqual(post.call_args.kwargs["headers"], EXPECTED_HEADERS)
        self.assertEqual(post.call_args.kwargs["params"]["fencing_generation"], 0)

    def test_order_status_and_release_calls_send_internal_token(self):
        reservation = {
            "reservation_id": "stable-reservation",
            "product_id": 41,
            "quantity": 1,
        }
        status_response = FakeResponse(200, {
            **reservation,
            "status": "RESERVED",
        })
        with patch.object(order_service.httpx, "get", return_value=status_response) as get:
            self.assertEqual(order_service.get_product_reservation_status(reservation), "RESERVED")
        self.assertEqual(get.call_args.kwargs["headers"], EXPECTED_HEADERS)

        records = [{**reservation, "state": "RESERVED"}]
        item = {**reservation, "reservation_index": 0}
        operation_state = {"tracking_failed": False, "reservation_records": records}
        with patch.object(
            order_service.httpx,
            "post",
            return_value=FakeResponse(200, {"status": "RELEASED"}),
        ) as post, patch.object(order_service, "set_reservation_state"):
            order_service.release_reserved_stock([item], 31, records, operation_state)
        self.assertEqual(post.call_args.kwargs["headers"], EXPECTED_HEADERS)

    def test_order_service_missing_token_fails_before_claiming_order(self):
        with patch.dict(os.environ, {"ORDER_SERVICE_TOKEN": ""}), \
             patch.object(order_service, "create_idempotency_record") as claim:
            with self.assertRaises(HTTPException) as raised:
                order_service.create_order(
                    order_service.OrderCreate(
                        user_id=7,
                        items=[order_service.OrderItemCreate(product_id=41, quantity=1)],
                    ),
                    Mock(headers={"Idempotency-Key": "test-key"}),
                    {"user_id": 7},
                )

        self.assertEqual(raised.exception.status_code, 503)
        claim.assert_not_called()

    def test_worker_sends_internal_token_for_release(self):
        response = FakeResponse(503, text="temporary failure")
        task = (5, "stable-reservation", 41, 1, "RELEASE", 1)
        with patch.object(reconciliation_worker.httpx, "post", return_value=response) as post, \
             patch.object(reconciliation_worker, "schedule_retry"):
            reconciliation_worker.process_task(task)

        self.assertEqual(post.call_args.kwargs["headers"], EXPECTED_HEADERS)
        self.assertEqual(post.call_args.kwargs["params"]["fencing_generation"], 0)

    def test_worker_missing_token_schedules_retry_without_network_call(self):
        task = (5, "stable-reservation", 41, 1, "RELEASE", 1)
        with patch.dict(os.environ, {"ORDER_SERVICE_TOKEN": ""}), \
             patch.object(reconciliation_worker, "schedule_retry") as retry, \
             patch.object(reconciliation_worker.httpx, "post") as post:
            reconciliation_worker.process_task(task)

        post.assert_not_called()
        retry.assert_called_once()
        self.assertIn("authentication is not configured", str(retry.call_args.args[2]))


if __name__ == "__main__":
    unittest.main()
