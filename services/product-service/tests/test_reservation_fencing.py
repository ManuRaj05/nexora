import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException


SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import main as product_service


RESERVATION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class MemoryDatabase:
    def __init__(self):
        self.state = {
            "products": {41: {"name": "Test product", "stock": 5}},
            "reservations": {},
            "operations": {},
        }
        self.fail_operation_insert = False

    def connect(self):
        return MemoryConnection(self)


class MemoryConnection:
    def __init__(self, database):
        self.database = database
        self.state = None
        self.cursor_instance = None

    def __enter__(self):
        self.state = copy.deepcopy(self.database.state)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.database.state = self.state
        return False

    def cursor(self):
        self.cursor_instance = MemoryCursor(self)
        return self.cursor_instance


class MemoryCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        state = self.connection.state
        self.result = None
        self.rowcount = 0

        if "pg_advisory_xact_lock" in sql:
            return
        if "FROM reservation_operations" in sql:
            row = state["operations"].get(params[0])
            if row is not None:
                self.result = (
                    row["product_id"], row["quantity"], row["generation"],
                    row["status"], row["created_at"],
                )
            return
        if "FROM stock_reservations" in sql:
            row = state["reservations"].get(params[0])
            if row is not None:
                self.result = (row["product_id"], row["quantity"], row["status"])
                if "created_at" in sql:
                    self.result += (row["created_at"],)
            return
        if sql.startswith("UPDATE products SET stock = stock -"):
            quantity, product_id, minimum = params
            product = state["products"].get(product_id)
            if product is not None and product["stock"] >= minimum:
                product["stock"] -= quantity
                self.result = (product_id, product["name"], product["stock"])
            return
        if sql.startswith("UPDATE products SET stock = stock +"):
            quantity, product_id = params
            product = state["products"].get(product_id)
            if product is not None:
                product["stock"] += quantity
                self.result = (product_id, product["name"], product["stock"])
            return
        if sql.startswith("SELECT id, name, stock FROM products"):
            product_id = params[0]
            product = state["products"].get(product_id)
            if product is not None:
                self.result = (product_id, product["name"], product["stock"])
            return
        if sql.startswith("SELECT id FROM products"):
            product_id = params[0]
            if product_id in state["products"]:
                self.result = (product_id,)
            return
        if sql.startswith("INSERT INTO stock_reservations"):
            reservation_id, product_id, quantity = params
            if reservation_id in state["reservations"]:
                raise RuntimeError("simulated stock_reservations primary-key conflict")
            state["reservations"][reservation_id] = {
                "product_id": product_id,
                "quantity": quantity,
                "status": "RESERVED",
                "created_at": None,
            }
            self.rowcount = 1
            return
        if sql.startswith("INSERT INTO reservation_operations"):
            if ", 0, %s, COALESCE" in sql:
                reservation_id, product_id, quantity, status, created_at = params
                generation = 0
                if reservation_id in state["operations"]:
                    return
                if self.connection.database.fail_operation_insert:
                    raise RuntimeError("simulated ledger insert failure")
                state["operations"][reservation_id] = {
                    "product_id": product_id,
                    "quantity": quantity,
                    "generation": generation,
                    "status": status,
                    "created_at": created_at,
                }
                self.rowcount = 1
            else:
                self.assert_conflict_update_is_fenced(sql)
                reservation_id, product_id, quantity, generation, status = params
                created_at = None
                existing = state["operations"].get(reservation_id)
                if existing is None:
                    if self.connection.database.fail_operation_insert:
                        raise RuntimeError("simulated ledger insert failure")
                    state["operations"][reservation_id] = {
                        "product_id": product_id,
                        "quantity": quantity,
                        "generation": generation,
                        "status": status,
                        "created_at": created_at,
                    }
                    self.rowcount = 1
                else:
                    transition_allowed = (
                        existing["status"] == status
                        or (existing["status"] == "RESERVED" and status == "RELEASED")
                    )
                    if existing["generation"] <= generation and transition_allowed:
                        existing.update({
                            "product_id": product_id,
                            "quantity": quantity,
                            "generation": generation,
                            "status": status,
                        })
                        self.rowcount = 1
            return
        if sql.startswith("UPDATE stock_reservations SET status = 'RELEASED'"):
            state["reservations"][params[0]]["status"] = "RELEASED"
            self.rowcount = 1
            return
        raise AssertionError(f"Unexpected SQL in mocked database: {sql}")

    def assert_conflict_update_is_fenced(self, sql):
        self.connection.database.assert_fenced_upsert = (
            "ON CONFLICT (reservation_id) DO UPDATE" in sql
            and "reservation_operations.fencing_generation <= EXCLUDED.fencing_generation" in sql
            and "reservation_operations.status = EXCLUDED.status" in sql
            and "reservation_operations.status = 'RESERVED'" in sql
            and "EXCLUDED.status = 'RELEASED'" in sql
        )
        if not self.connection.database.assert_fenced_upsert:
            raise AssertionError("Reservation ledger upsert lacks generation/state fencing")

    def fetchone(self):
        return self.result


class ReservationFencingTests(unittest.TestCase):
    def setUp(self):
        self.database = MemoryDatabase()
        self.connection_patch = patch.object(
            product_service, "get_connection", side_effect=self.database.connect
        )
        self.connection_patch.start()
        self.token_patch = patch.dict(os.environ, {"ORDER_SERVICE_TOKEN": "test-service-token"})
        self.token_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.addCleanup(self.token_patch.stop)

    def reserve(self, generation=0, reservation_id=RESERVATION_ID, product_id=41, quantity=1, token="test-service-token"):
        return product_service.reserve_stock(
            product_id, quantity, reservation_id, generation, token
        )

    def release(self, generation=0, reservation_id=RESERVATION_ID, product_id=41, quantity=1, token="test-service-token"):
        return product_service.release_stock(
            product_id, quantity, reservation_id, generation, token
        )

    def cancel(self, generation, reservation_id=RESERVATION_ID, product_id=41, quantity=1, token="test-service-token"):
        return product_service.cancel_reservation(
            product_id, quantity, reservation_id, generation, token
        )

    def test_stale_generation_is_rejected(self):
        self.cancel(2)
        initial_stock = self.database.state["products"][41]["stock"]

        with self.assertRaises(HTTPException) as raised:
            self.reserve(generation=1)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.database.state["products"][41]["stock"], initial_stock)

    def test_generation_is_monotonic_across_valid_operations(self):
        self.reserve(generation=5)
        self.reserve(generation=8)

        with self.assertRaises(HTTPException) as raised:
            self.release(generation=7)

        operation = self.database.state["operations"][RESERVATION_ID]
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(operation["generation"], 8)
        self.assertEqual(operation["status"], "RESERVED")
        self.assertEqual(self.database.state["products"][41]["stock"], 4)

    def test_upsert_rejects_lower_generation_and_preserves_existing_state(self):
        self.database.state["operations"][RESERVATION_ID] = {
            "product_id": 41,
            "quantity": 1,
            "generation": 9,
            "status": "RESERVED",
            "created_at": None,
        }

        with self.assertRaises(HTTPException) as raised:
            with self.database.connect() as connection:
                with connection.cursor() as cursor:
                    product_service.update_operation(
                        cursor, RESERVATION_ID, 41, 1, 8, "RELEASED"
                    )

        self.assertEqual(raised.exception.status_code, 409)
        operation = self.database.state["operations"][RESERVATION_ID]
        self.assertEqual(operation["generation"], 9)
        self.assertEqual(operation["status"], "RESERVED")

    def test_terminal_state_cannot_be_reopened_by_a_higher_generation(self):
        self.cancel(4)

        with self.assertRaises(HTTPException) as raised:
            with self.database.connect() as connection:
                with connection.cursor() as cursor:
                    product_service.update_operation(
                        cursor, RESERVATION_ID, 41, 1, 5, "RESERVED"
                    )

        self.assertEqual(raised.exception.status_code, 409)
        operation = self.database.state["operations"][RESERVATION_ID]
        self.assertEqual(operation["generation"], 4)
        self.assertEqual(operation["status"], "CANCELLED")

    def test_repeated_release_does_not_restore_stock_twice(self):
        self.reserve(generation=0)
        self.release(generation=0)
        restored_stock = self.database.state["products"][41]["stock"]

        result = self.release(generation=0)

        self.assertTrue(result["already_released"])
        self.assertEqual(result["status"], "RELEASED")
        self.assertEqual(self.database.state["products"][41]["stock"], restored_stock)

    def test_release_does_not_report_a_tombstone_as_stock_released(self):
        self.cancel(3)

        result = self.release(generation=3)

        self.assertEqual(result["status"], "CANCELLED")
        self.assertFalse(result["already_released"])
        self.assertTrue(result["already_cancelled"])

    def test_cancel_of_missing_reservation_creates_tombstone(self):
        result = self.cancel(3)

        operation = self.database.state["operations"][RESERVATION_ID]
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(operation["generation"], 3)
        self.assertEqual(operation["status"], "CANCELLED")
        self.assertEqual(self.database.state["products"][41]["stock"], 5)

    def test_repeated_cancel_is_idempotent(self):
        first = self.cancel(3)
        second = self.cancel(3)

        self.assertFalse(first["already_cancelled"])
        self.assertTrue(second["already_cancelled"])
        self.assertEqual(second["status"], "CANCELLED")
        self.assertEqual(len(self.database.state["operations"]), 1)
        self.assertEqual(self.database.state["products"][41]["stock"], 5)

    def test_cancel_of_active_reservation_restores_stock_only_once(self):
        self.reserve(generation=0)
        first = self.cancel(2)
        restored_stock = self.database.state["products"][41]["stock"]
        second = self.cancel(2)

        self.assertEqual(first["status"], "RELEASED")
        self.assertEqual(second["status"], "RELEASED")
        self.assertEqual(self.database.state["products"][41]["stock"], restored_stock)

    def test_delayed_stale_reserve_after_cancel_cannot_change_stock(self):
        self.cancel(4)

        with self.assertRaises(HTTPException) as raised:
            self.reserve(generation=3)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.database.state["products"][41]["stock"], 5)
        self.assertNotIn(RESERVATION_ID, self.database.state["reservations"])

    def test_mismatched_reservation_details_are_rejected(self):
        self.reserve(generation=0)

        with self.assertRaises(HTTPException) as raised:
            self.release(generation=0, quantity=2)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.database.state["products"][41]["stock"], 4)

    def test_legacy_reservation_is_imported_at_generation_zero(self):
        self.database.state["reservations"][RESERVATION_ID] = {
            "product_id": 41,
            "quantity": 1,
            "status": "RESERVED",
            "created_at": None,
        }

        result = self.reserve(generation=0)

        operation = self.database.state["operations"][RESERVATION_ID]
        self.assertTrue(result["already_reserved"])
        self.assertEqual(operation["generation"], 0)
        self.assertEqual(operation["status"], "RESERVED")
        self.assertEqual(self.database.state["products"][41]["stock"], 5)

    def test_legacy_reserved_row_without_ledger_can_be_released_once(self):
        self.database.state["products"][41]["stock"] = 4
        self.database.state["reservations"][RESERVATION_ID] = {
            "product_id": 41,
            "quantity": 1,
            "status": "RESERVED",
            "created_at": None,
        }

        first = self.release(generation=0)
        second = self.release(generation=0)

        self.assertFalse(first["already_released"])
        self.assertTrue(second["already_released"])
        self.assertEqual(self.database.state["products"][41]["stock"], 5)
        self.assertEqual(self.database.state["operations"][RESERVATION_ID]["status"], "RELEASED")

    def test_legacy_released_row_without_ledger_does_not_restore_stock(self):
        self.database.state["reservations"][RESERVATION_ID] = {
            "product_id": 41,
            "quantity": 1,
            "status": "RELEASED",
            "created_at": None,
        }

        result = self.release(generation=0)

        self.assertTrue(result["already_released"])
        self.assertEqual(self.database.state["products"][41]["stock"], 5)
        self.assertEqual(self.database.state["operations"][RESERVATION_ID]["status"], "RELEASED")

    def test_ledger_reservation_state_mismatch_is_rejected_without_stock_change(self):
        self.database.state["reservations"][RESERVATION_ID] = {
            "product_id": 41,
            "quantity": 1,
            "status": "RELEASED",
            "created_at": None,
        }
        self.database.state["operations"][RESERVATION_ID] = {
            "product_id": 41,
            "quantity": 1,
            "generation": 0,
            "status": "RESERVED",
            "created_at": None,
        }

        with self.assertRaises(HTTPException) as raised:
            self.release(generation=0)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("inconsistent", raised.exception.detail.lower())
        self.assertEqual(self.database.state["products"][41]["stock"], 5)
        self.assertEqual(self.database.state["operations"][RESERVATION_ID]["status"], "RESERVED")

    def test_ledger_released_with_reserved_row_cannot_restore_stock_twice(self):
        self.database.state["reservations"][RESERVATION_ID] = {
            "product_id": 41,
            "quantity": 1,
            "status": "RESERVED",
            "created_at": None,
        }
        self.database.state["operations"][RESERVATION_ID] = {
            "product_id": 41,
            "quantity": 1,
            "generation": 0,
            "status": "RELEASED",
            "created_at": None,
        }

        with self.assertRaises(HTTPException) as raised:
            self.release(generation=0)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.database.state["products"][41]["stock"], 5)

    def test_reservation_endpoints_reject_missing_or_invalid_credentials(self):
        for token in (None, "wrong-token"):
            with self.subTest(token="missing" if token is None else "invalid"):
                with self.assertRaises(HTTPException) as raised:
                    self.reserve(token=token)
                self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(self.database.state["products"][41]["stock"], 5)

    def test_all_reservation_routes_require_internal_credentials(self):
        calls = (
            lambda: product_service.reserve_stock(41, 1, RESERVATION_ID, 0, None),
            lambda: product_service.release_stock(41, 1, RESERVATION_ID, 0, None),
            lambda: product_service.cancel_reservation(41, 1, RESERVATION_ID, 0, None),
            lambda: product_service.get_reservation_status(41, RESERVATION_ID, 0, None),
        )
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(HTTPException) as raised:
                    call()
                self.assertEqual(raised.exception.status_code, 401)

    def test_missing_config_fails_closed(self):
        with patch.dict(os.environ, {"ORDER_SERVICE_TOKEN": ""}):
            with self.assertRaises(HTTPException) as raised:
                self.reserve()
        self.assertEqual(raised.exception.status_code, 503)

    def test_stock_and_ledger_updates_roll_back_together(self):
        self.database.fail_operation_insert = True

        with self.assertRaises(RuntimeError):
            self.reserve()

        self.assertEqual(self.database.state["products"][41]["stock"], 5)
        self.assertEqual(self.database.state["reservations"], {})
        self.assertEqual(self.database.state["operations"], {})


if __name__ == "__main__":
    unittest.main()
