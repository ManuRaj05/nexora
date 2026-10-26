import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, call, patch

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse


SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import main as order_service


class FakeResponse:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self.body = body
        self.text = text

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeCursor:
    def __init__(self, fetches=None, on_execute=None):
        self.fetches = list(fetches or [])
        self.on_execute = on_execute
        self.rowcount = 1
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if self.on_execute:
            self.on_execute(self, query, params)

    def fetchone(self):
        return self.fetches.pop(0) if self.fetches else None


class FakeConnection:
    def __init__(self, cursor=None, exit_error=None):
        self.fake_cursor = cursor or FakeCursor()
        self.exit_error = exit_error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None and self.exit_error:
            raise self.exit_error
        return False

    def cursor(self):
        return self.fake_cursor


class ConcurrentClaimDatabase:
    """Small in-memory stand-in for the unique INSERT conflict behavior."""

    def __init__(self):
        self.lock = threading.Lock()
        self.rows = {}
        self.next_id = 1

    def connection(self):
        return FakeConnection(FakeCursor(on_execute=self.execute))

    def execute(self, cursor, query, params):
        if "INSERT INTO order_idempotency" in query:
            user_id, key_digest, request_digest, payload, records = params
            unique_key = (user_id, key_digest)
            with self.lock:
                if unique_key in self.rows:
                    cursor.fetches = [None]
                    return
                row = {
                    "id": self.next_id,
                    "request_digest": request_digest,
                    "state": "IN_PROGRESS",
                    "response_status": None,
                    "response_body": None,
                    "reservation_ids": records.obj,
                }
                self.rows[unique_key] = row
                self.next_id += 1
                cursor.fetches = [(row["id"], row["reservation_ids"])]
        elif "SELECT id, request_digest, state" in query:
            user_id, key_digest = params
            row = self.rows[(user_id, key_digest)]
            cursor.fetches = [(
                row["id"], row["request_digest"], row["state"],
                row["response_status"], row["response_body"],
                row["reservation_ids"],
            )]


def order_request(items=None):
    return order_service.OrderCreate(
        user_id=7,
        items=items or [order_service.OrderItemCreate(product_id=41, quantity=1)],
    )


def request_with_key(key="request-key-1"):
    return Mock(headers={"Idempotency-Key": key})


def product_row(product_id=41):
    return [product_id, "Test product", "Description", 12.5, 8, "Test"]


def reservation_response(reservation_id, product_id=41, status="RESERVED"):
    return FakeResponse(200, {
        "reservation_id": reservation_id,
        "product_id": product_id,
        "name": "Test product",
        "remaining_stock": 7,
        "already_reserved": status == "RESERVED",
    })


def status_response(reservation_id, status, product_id=41, quantity=1):
    return FakeResponse(200, {
        "reservation_id": reservation_id,
        "product_id": product_id,
        "quantity": quantity,
        "status": status,
        "created_at": "2026-01-01T00:00:00Z",
    })


class IdempotencyHelperTests(unittest.TestCase):
    def test_same_key_and_payload_replay_completed_response(self):
        digest = b"d" * 32
        body = {"id": 91, "user_id": 7, "items": []}
        cursor = FakeCursor(fetches=[None, (12, digest, "COMPLETED", 200, body, [])])

        with patch.object(order_service, "get_connection", return_value=FakeConnection(cursor)):
            _, _, replay = order_service.create_idempotency_record(
                7, b"k" * 32, digest, {"user_id": 7, "items": []}, []
            )

        self.assertIsInstance(replay, JSONResponse)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.body, b'{"id":91,"user_id":7,"items":[]}')

    def test_same_key_with_different_payload_returns_409(self):
        cursor = FakeCursor(fetches=[None, (12, b"a" * 32, "COMPLETED", 200, {}, [])])

        with patch.object(order_service, "get_connection", return_value=FakeConnection(cursor)):
            with self.assertRaises(HTTPException) as raised:
                order_service.create_idempotency_record(
                    7, b"k" * 32, b"b" * 32, {"user_id": 7, "items": []}, []
                )

        self.assertEqual(raised.exception.status_code, 409)

    def test_concurrent_claims_create_one_idempotency_record(self):
        database = ConcurrentClaimDatabase()
        barrier = threading.Barrier(2)
        args = (
            7,
            b"k" * 32,
            b"d" * 32,
            {"user_id": 7, "items": [{"product_id": 41, "quantity": 1}]},
            [{"reservation_id": "stable-id", "state": "NOT_STARTED"}],
        )

        def claim():
            barrier.wait()
            try:
                return order_service.create_idempotency_record(*args)
            except HTTPException as error:
                return error

        with patch.object(order_service, "get_connection", side_effect=database.connection):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: claim(), range(2)))

        created = [result for result in results if isinstance(result, tuple)]
        conflicts = [result for result in results if isinstance(result, HTTPException)]
        self.assertEqual(len(database.rows), 1)
        self.assertEqual(len(created), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].status_code, 409)


class RecoveryFlowTests(unittest.TestCase):
    def _claim_side_effect(self, user_id, key_digest, request_digest, payload, records):
        return 22, records, None

    def _set_state_side_effect(self, idempotency_id, records, index, state, operation_state):
        records[index]["state"] = state

    def test_timeout_then_reserved_status_triggers_compensation(self):
        saved_failure = Mock()
        get_responses = [
            FakeResponse(200, [7, "customer"]),
            FakeResponse(200, product_row()),
            status_response("stable-reservation", "RESERVED"),
        ]
        post_effects = [
            httpx.ReadTimeout("reserve timed out"),
            FakeResponse(200, {"status": "RELEASED"}),
        ]

        def claim_with_stable_record(user_id, key_digest, digest, payload, records):
            records[0]["reservation_id"] = "stable-reservation"
            return 22, records, None

        with patch.object(order_service, "create_idempotency_record", side_effect=claim_with_stable_record), \
             patch.object(order_service, "set_reservation_state", side_effect=self._set_state_side_effect) as state_update, \
             patch.object(order_service, "save_failed_response", saved_failure), \
             patch.object(order_service.httpx, "get", side_effect=get_responses), \
             patch.object(order_service.httpx, "post", side_effect=post_effects) as post:
            with self.assertRaises(HTTPException) as raised:
                order_service.create_order(order_request(), request_with_key(), {"user_id": 7})

        self.assertEqual(raised.exception.status_code, 504)
        self.assertIn("RESERVING", [entry.args[3] for entry in state_update.call_args_list])
        self.assertEqual(post.call_count, 2)
        self.assertIn("/reserve", post.call_args_list[0].args[0])
        self.assertIn("/release", post.call_args_list[1].args[0])
        self.assertEqual(saved_failure.call_args.args[1], 504)

    def test_unresolved_reservation_never_becomes_failed(self):
        records = []

        def claim_with_stable_record(user_id, key_digest, digest, payload, reservation_records):
            reservation_records[0]["reservation_id"] = "stable-reservation"
            records.extend(reservation_records)
            return 23, reservation_records, None

        mark_recovery = Mock()
        save_failure = Mock()
        get_responses = [
            FakeResponse(200, [7, "customer"]),
            FakeResponse(200, product_row()),
            FakeResponse(404, {"detail": "Reservation not found"}),
            FakeResponse(404, {"detail": "Reservation not found"}),
        ]
        post_effects = [
            httpx.ReadTimeout("reserve timed out"),
            FakeResponse(404, {"detail": "Reservation not found"}),
        ]

        with patch.object(order_service, "create_idempotency_record", side_effect=claim_with_stable_record), \
             patch.object(order_service, "set_reservation_state", side_effect=self._set_state_side_effect), \
             patch.object(order_service, "mark_recovery_required", mark_recovery), \
             patch.object(order_service, "save_failed_response", save_failure), \
             patch.object(order_service, "save_reconciliation_task"), \
             patch.object(order_service.httpx, "get", side_effect=get_responses), \
             patch.object(order_service.httpx, "post", side_effect=post_effects):
            with self.assertRaises(HTTPException) as raised:
                order_service.create_order(order_request(), request_with_key(), {"user_id": 7})

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(records[0]["state"], "UNKNOWN")
        mark_recovery.assert_called_once_with(23)
        save_failure.assert_not_called()

    def test_reserve_404_checks_status_and_compensates_active_reservation(self):
        saved_failure = Mock()
        state_updates = []

        def claim_with_stable_record(user_id, key_digest, digest, payload, records):
            records[0]["reservation_id"] = "stable-reservation"
            return 26, records, None

        def record_state(idempotency_id, records, index, state, operation_state):
            records[index]["state"] = state
            state_updates.append(state)

        get_responses = [
            FakeResponse(200, [7, "customer"]),
            FakeResponse(200, product_row()),
            status_response("stable-reservation", "RESERVED"),
        ]
        post_effects = [
            FakeResponse(404, {"detail": "Product not found"}),
            FakeResponse(200, {"status": "RELEASED"}),
        ]

        with patch.object(order_service, "create_idempotency_record", side_effect=claim_with_stable_record), \
             patch.object(order_service, "set_reservation_state", side_effect=record_state), \
             patch.object(order_service, "save_failed_response", saved_failure), \
             patch.object(order_service.httpx, "get", side_effect=get_responses) as get, \
             patch.object(order_service.httpx, "post", side_effect=post_effects) as post:
            with self.assertRaises(HTTPException) as raised:
                order_service.create_order(order_request(), request_with_key(), {"user_id": 7})

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(get.call_count, 3)
        self.assertIn("/reservations/stable-reservation", get.call_args_list[2].args[0])
        self.assertEqual(post.call_count, 2)
        self.assertIn("/reserve", post.call_args_list[0].args[0])
        self.assertIn("/release", post.call_args_list[1].args[0])
        self.assertEqual(state_updates, ["RESERVING", "RESERVED", "RELEASED"])
        saved_failure.assert_called_once_with(26, 404, {"detail": "Product 41 not found"})

    def test_partial_compensation_tracks_unresolved_reservation(self):
        records = [
            {"reservation_id": "first", "product_id": 41, "quantity": 1, "state": "RESERVED"},
            {"reservation_id": "second", "product_id": 42, "quantity": 1, "state": "RESERVED"},
        ]
        items = [
            {"reservation_id": "first", "product_id": 41, "quantity": 1, "reservation_index": 0},
            {"reservation_id": "second", "product_id": 42, "quantity": 1, "reservation_index": 1},
        ]
        operation_state = {"tracking_failed": False, "reservation_records": records}
        release_response = FakeResponse(200, {"status": "RELEASED"})

        with patch.object(order_service.httpx, "post", side_effect=[release_response, httpx.ReadTimeout("release timed out")]), \
             patch.object(order_service, "get_product_reservation_status", return_value="RESERVED"), \
             patch.object(order_service, "set_reservation_state", side_effect=self._set_state_side_effect), \
             patch.object(order_service, "save_reconciliation_task") as task:
            outcomes = order_service.release_reserved_stock(items, 24, records, operation_state)

        self.assertEqual(records[1]["state"], "RELEASED")
        self.assertEqual(records[0]["state"], "RESERVED")
        self.assertEqual([result["state"] for result in outcomes], ["RELEASED", "RESERVED"])
        task.assert_called_once()
        self.assertFalse(order_service.reservations_are_resolved(records, operation_state))

    def test_committed_order_is_not_compensated_after_lost_acknowledgment(self):
        records = [{
            "reservation_id": "stable-reservation",
            "product_id": 41,
            "quantity": 1,
            "state": "NOT_STARTED",
        }]
        cursor = FakeCursor(fetches=[(93, 7, 12.5, "PENDING", None)])
        committed_response = {
            "id": 93,
            "user_id": 7,
            "total_amount": 12.5,
            "status": "PENDING",
            "items": [{"product_id": 41, "quantity": 1, "price": 12.5}],
        }
        connection = FakeConnection(cursor, exit_error=RuntimeError("lost commit acknowledgment"))
        user_response = FakeResponse(200, [7, "customer"])
        product_response = FakeResponse(200, product_row())
        reserve_response = reservation_response("stable-reservation")
        state = {"tracking_failed": False, "reservation_records": records}

        with patch.object(order_service, "set_reservation_state", side_effect=self._set_state_side_effect), \
             patch.object(order_service, "get_connection", return_value=connection), \
             patch.object(order_service, "read_idempotency_outcome", return_value=("COMPLETED", 200, committed_response)), \
             patch.object(order_service.httpx, "get", side_effect=[user_response, product_response]), \
             patch.object(order_service.httpx, "post", return_value=reserve_response) as post:
            result = order_service._process_order(
                order_request(), {"user_id": 7}, records, 25, state
            )

        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.body, JSONResponse(content=committed_response).body)
        self.assertEqual(post.call_count, 1)
        self.assertIn("/reserve", post.call_args.args[0])

    def test_completed_idempotency_update_links_created_order(self):
        order_id = 987
        cursor = FakeCursor(fetches=[(order_id, 7, 12.5, "PENDING", None)])
        records = [{
            "reservation_id": "stable-reservation",
            "product_id": 41,
            "quantity": 1,
            "state": "NOT_STARTED",
        }]
        operation_state = {"tracking_failed": False, "reservation_records": records}

        with patch.object(
            order_service,
            "set_reservation_state",
            side_effect=self._set_state_side_effect,
        ), patch.object(
            order_service,
            "get_connection",
            return_value=FakeConnection(cursor),
        ), patch.object(
            order_service.httpx,
            "get",
            side_effect=[
                FakeResponse(200, [7, "customer"]),
                FakeResponse(200, product_row()),
            ],
        ), patch.object(
            order_service.httpx,
            "post",
            return_value=reservation_response("stable-reservation"),
        ):
            result = order_service._process_order(
                order_request(),
                {"user_id": 7},
                records,
                27,
                operation_state,
            )

        self.assertEqual(result["id"], 987)
        update_query, update_params = next(
            (query, params)
            for query, params in cursor.queries
            if "UPDATE order_idempotency" in query
            and "state = 'COMPLETED'" in query
        )
        self.assertIn("order_id = %s", " ".join(update_query.split()))
        self.assertEqual(update_params[1], 987)

    def test_state_update_failure_does_not_mark_record_failed(self):
        recovery = Mock()
        failed = Mock()

        def fail_before_reservation(order, identity, records, idempotency_id, operation_state):
            order_service.set_reservation_state(
                idempotency_id, records, 0, "RESERVING", operation_state
            )

        with patch.object(order_service, "create_idempotency_record", side_effect=self._claim_side_effect), \
             patch.object(order_service, "_process_order", side_effect=fail_before_reservation), \
             patch.object(order_service, "get_connection", side_effect=RuntimeError("database unavailable")), \
             patch.object(order_service, "mark_recovery_required", recovery), \
             patch.object(order_service, "save_failed_response", failed):
            with self.assertRaises(HTTPException) as raised:
                order_service.create_order(order_request(), request_with_key(), {"user_id": 7})

        self.assertEqual(raised.exception.status_code, 500)
        recovery.assert_called_once_with(22)
        failed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
