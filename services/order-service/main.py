import hashlib
import json
import os
from uuid import uuid4
from fastapi import Depends, FastAPI
from fastapi import Request
from pydantic import BaseModel
from typing import List
import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from database import get_connection
import jwt
from psycopg.types.json import Jsonb

app = FastAPI()
bearer_scheme = HTTPBearer(auto_error=False)


def product_service_headers():
    token = os.getenv("ORDER_SERVICE_TOKEN")
    if not token or not token.strip():
        raise HTTPException(
            status_code=503,
            detail="Product Service authentication is not configured",
        )
    return {"X-Order-Service-Token": token}


def get_current_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    secret = os.getenv("JWT_SECRET")
    if not secret or not secret.strip():
        raise HTTPException(
            status_code=503,
            detail="Token verification is not configured",
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=["HS256"],
            options={"require": ["user_id", "exp"]},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id")
    if (
        isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or user_id <= 0
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"user_id": user_id}


def get_existing_user_identity(
    identity: dict = Depends(get_current_identity),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    try:
        response = httpx.get(
            "http://127.0.0.1:8000/users/me",
            headers={"Authorization": f"Bearer {credentials.credentials}"},
            timeout=5.0,
        )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="User Service is unavailable")

    if response.status_code in (401, 404):
        raise HTTPException(
            status_code=401,
            detail="User account is unavailable",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=503, detail="Unable to verify user identity")

    try:
        verified_identity = response.json()
    except (ValueError, AttributeError):
        raise HTTPException(status_code=503, detail="Unable to verify user identity")

    verified_user_id = verified_identity.get("user_id") if isinstance(verified_identity, dict) else None
    if isinstance(verified_user_id, bool) or not isinstance(verified_user_id, int):
        raise HTTPException(status_code=503, detail="Unable to verify user identity")
    if verified_user_id != identity["user_id"]:
        raise HTTPException(
            status_code=401,
            detail="User account is unavailable",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return identity

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int


class OrderCreate(BaseModel):
    user_id: int
    items: List[OrderItemCreate]

@app.get("/")
def root():
    return {"message": "Nexora Order Service is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}

def get_product_reservation_status(item):
    try:
        response = httpx.get(
            f"http://127.0.0.1:8001/products/{item['product_id']}/reservations/"
            f"{item['reservation_id']}",
            headers=product_service_headers(),
            timeout=5.0,
        )
    except httpx.RequestError:
        return "UNKNOWN"

    if response.status_code == 404:
        return "MISSING"
    if response.status_code != 200:
        return "UNKNOWN"

    try:
        result = response.json()
    except (ValueError, AttributeError):
        return "UNKNOWN"

    if (
        not isinstance(result, dict)
        or result.get("reservation_id") != item["reservation_id"]
        or result.get("product_id") != item["product_id"]
        or result.get("quantity") != item["quantity"]
    ):
        return "UNKNOWN"

    status = result.get("status")
    return status if status in ("RESERVED", "RELEASED") else "UNKNOWN"

def set_reservation_state(idempotency_id, reservation_records, index, state, operation_state):
    reservation_records[index]["state"] = state
    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE order_idempotency
                    SET reservation_ids = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND state = 'IN_PROGRESS';
                    """,
                    (Jsonb(reservation_records), idempotency_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Idempotency record is not in progress")
    except Exception:
        operation_state["tracking_failed"] = True
        raise

def save_reconciliation_task(item, error_message):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO reconciliation_tasks
                (reservation_id, product_id, quantity, action,
                 status, last_error)
                VALUES (%s, %s, %s, 'RELEASE', 'PENDING', %s)
                ON CONFLICT (reservation_id, action)
                DO UPDATE SET
                    status = CASE
                        WHEN reconciliation_tasks.status = 'COMPLETED'
                        THEN 'COMPLETED'
                        ELSE 'PENDING'
                    END,
                    next_retry_at = CASE
                        WHEN reconciliation_tasks.status = 'COMPLETED'
                        THEN reconciliation_tasks.next_retry_at
                        ELSE CURRENT_TIMESTAMP
                    END,
                    last_error = CASE
                        WHEN reconciliation_tasks.status = 'COMPLETED'
                        THEN reconciliation_tasks.last_error
                        ELSE EXCLUDED.last_error
                    END,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (
                    item["reservation_id"],
                    item["product_id"],
                    item["quantity"],
                    error_message[:2000],
                ),
            )

def release_reserved_stock(reserved_items, idempotency_id, reservation_records, operation_state):
    outcomes = []

    for item in reversed(reserved_items):
        error_message = None
        release_confirmed = False

        try:
            response = httpx.post(
                f"http://127.0.0.1:8001/products/{item['product_id']}/release",
                params={
                    "quantity": item["quantity"],
                    "reservation_id": item["reservation_id"],
                },
                headers=product_service_headers(),
                timeout=5.0,
            )
            if response.status_code == 200:
                try:
                    release_confirmed = response.json().get("status") == "RELEASED"
                except (ValueError, AttributeError):
                    error_message = "Product Service returned an unreadable release response"
            else:
                error_message = (
                    f"Product Service returned HTTP {response.status_code}: "
                    f"{response.text}"
                )
        except httpx.RequestError as exc:
            error_message = f"Product Service release outcome is uncertain: {exc}"

        if not release_confirmed:
            status = get_product_reservation_status(item)
            if status == "RELEASED":
                release_confirmed = True
            elif status == "RESERVED":
                set_reservation_state(
                    idempotency_id,
                    reservation_records,
                    item["reservation_index"],
                    "RESERVED",
                    operation_state,
                )
            else:
                set_reservation_state(
                    idempotency_id,
                    reservation_records,
                    item["reservation_index"],
                    "UNKNOWN",
                    operation_state,
                )

        if release_confirmed:
            set_reservation_state(
                idempotency_id,
                reservation_records,
                item["reservation_index"],
                "RELEASED",
                operation_state,
            )
            outcomes.append({"reservation_id": item["reservation_id"], "state": "RELEASED"})
            continue

        if error_message is None:
            error_message = "Reservation release could not be confirmed"
        print(
            f"WARNING: Stock release is unresolved for product "
            f"{item['product_id']}: {error_message}"
        )

        try:
            save_reconciliation_task(item, error_message)
            print(f"Reconciliation task saved for reservation {item['reservation_id']}")
        except Exception:
            operation_state["tracking_failed"] = True
            print(
                f"CRITICAL: Could not save reconciliation task for "
                f"reservation {item['reservation_id']}"
            )

        outcomes.append({
            "reservation_id": item["reservation_id"],
            "state": reservation_records[item["reservation_index"]]["state"],
        })

    return outcomes

def normalized_order_payload(order, user_id):
    return {
        "user_id": user_id,
        "items": [
            {"product_id": item.product_id, "quantity": item.quantity}
            for item in order.items
        ],
    }

def json_digest(value):
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()

def create_idempotency_record(user_id, key_digest, request_digest, payload, reservation_records):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO order_idempotency
                (user_id, key_digest, request_digest, request_payload,
                 reservation_ids, state)
                VALUES (%s, %s, %s, %s, %s, 'IN_PROGRESS')
                ON CONFLICT (user_id, key_digest) DO NOTHING
                RETURNING id, reservation_ids;
                """,
                (
                    user_id,
                    key_digest,
                    request_digest,
                    Jsonb(payload),
                    Jsonb(reservation_records),
                ),
            )
            created = cursor.fetchone()

            if created is not None:
                return created[0], created[1], None

            cursor.execute(
                """
                SELECT id, request_digest, state, response_status,
                       response_body, reservation_ids
                FROM order_idempotency
                WHERE user_id = %s AND key_digest = %s;
                """,
                (user_id, key_digest),
            )
            existing = cursor.fetchone()

    if existing is None:
        raise HTTPException(
            status_code=503,
            detail="Could not confirm the idempotency record; retry with the same key",
        )

    if existing[1] != request_digest:
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used with a different order",
        )

    if existing[2] in ("COMPLETED", "FAILED"):
        return None, None, JSONResponse(
            status_code=existing[3],
            content=existing[4],
        )

    if existing[2] == "RECOVERY_REQUIRED":
        raise HTTPException(
            status_code=409,
            detail="This order requires recovery; do not resubmit it with a new key",
        )

    raise HTTPException(
        status_code=409,
        detail="An order with this Idempotency-Key is already in progress",
        headers={"Retry-After": "2"},
    )

def save_failed_response(idempotency_id, status_code, body):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE order_idempotency
                SET state = 'FAILED', response_status = %s,
                    response_body = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND state = 'IN_PROGRESS';
                """,
                (status_code, Jsonb(body), idempotency_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Idempotency record was not in progress")

def mark_recovery_required(idempotency_id):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE order_idempotency
                SET state = 'RECOVERY_REQUIRED', updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND state = 'IN_PROGRESS';
                """,
                (idempotency_id,),
            )

def read_idempotency_outcome(idempotency_id):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT state, response_status, response_body
                FROM order_idempotency
                WHERE id = %s
                FOR UPDATE;
                """,
                (idempotency_id,),
            )
            result = cursor.fetchone()

    if result is None:
        return "UNKNOWN", None, None
    if result[0] == "COMPLETED":
        return "COMPLETED", result[1], result[2]
    if result[0] == "IN_PROGRESS":
        return "NOT_COMMITTED", None, None
    return result[0], result[1], result[2]

def reservations_are_resolved(reservation_records, operation_state):
    return (
        not operation_state["tracking_failed"]
        and all(
            record["state"] in ("NOT_STARTED", "NOT_RESERVED", "RELEASED")
            for record in reservation_records
        )
    )

@app.post("/orders")
def create_order(
    order: OrderCreate,
    request: Request,
    identity: dict = Depends(get_current_identity),
):
    if order.user_id != identity["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="Customers may only create orders for themselves",
        )

    if not order.items:
        raise HTTPException(
            status_code=400,
            detail="Order must contain at least one item"
        )

    product_service_headers()

    idempotency_key = request.headers.get("Idempotency-Key")
    if (
        not idempotency_key
        or len(idempotency_key) > 255
        or any(character < "!" or character > "~" for character in idempotency_key)
    ):
        raise HTTPException(
            status_code=400,
            detail="A valid Idempotency-Key header is required",
        )

    payload = normalized_order_payload(order, identity["user_id"])
    request_digest = json_digest(payload)
    key_digest = hashlib.sha256(idempotency_key.encode("ascii")).digest()
    reservation_records = [
        {
            "reservation_id": str(uuid4()),
            "product_id": item.product_id,
            "quantity": item.quantity,
            "state": "NOT_STARTED",
        }
        for item in order.items
    ]
    idempotency_id, reservation_records, replay = create_idempotency_record(
        identity["user_id"],
        key_digest,
        request_digest,
        payload,
        reservation_records,
    )
    if replay is not None:
        return replay

    operation_state = {
        "tracking_failed": False,
        "reservation_records": reservation_records,
    }
    try:
        return _process_order(
            order,
            identity,
            reservation_records,
            idempotency_id,
            operation_state,
            request.headers.get("Authorization"),
        )
    except HTTPException as error:
        try:
            if reservations_are_resolved(reservation_records, operation_state):
                save_failed_response(
                    idempotency_id,
                    error.status_code,
                    {"detail": error.detail},
                )
            else:
                mark_recovery_required(idempotency_id)
        except Exception:
            print("WARNING: Idempotency state update failed; leaving the record nonterminal")
        raise
    except Exception:
        failure_detail = "Order creation failed; the outcome may require recovery"
        try:
            if reservations_are_resolved(reservation_records, operation_state):
                save_failed_response(
                    idempotency_id,
                    500,
                    {"detail": failure_detail},
                )
            else:
                mark_recovery_required(idempotency_id)
        except Exception:
            print("WARNING: Idempotency state update failed; leaving the record nonterminal")
        raise HTTPException(
            status_code=500,
            detail=failure_detail,
        )

def _process_order(order, identity, reservation_records, idempotency_id, operation_state, authorization=None):
    try:
        user_response = httpx.get(
            f"http://127.0.0.1:8000/users/{order.user_id}",
            headers={"Authorization": authorization} if authorization else None,
            timeout=5.0
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="User Service timed out"
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="User Service is unavailable"
        )

    if user_response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="User Service request failed"
        )

    user = user_response.json()

    if isinstance(user, dict) and "error" in user:
        raise HTTPException(
            status_code=404,
            detail=f"User {order.user_id} not found"
        )

    if not isinstance(user, list) or not user or user[0] != order.user_id:
        raise HTTPException(
            status_code=404,
            detail=f"User {order.user_id} not found"
        )

    total_amount = 0
    validated_items = []
    reserved_items = []

    def compensate(items):
        release_reserved_stock(
            items,
            idempotency_id,
            reservation_records,
            operation_state,
        )
        return reservations_are_resolved(reservation_records, operation_state)

    for item_index, item in enumerate(order.items):
        try:
            response = httpx.get(
                f"http://127.0.0.1:8001/products/{item.product_id}",
                timeout=5.0
            )
        
        except httpx.TimeoutException:
            released = compensate(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Product Service timed out, and stock compensation "
                        "was incomplete. Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=504,
                detail="Product Service timed out; reserved stock was released"
            )

        
        except httpx.RequestError:
            released = compensate(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Product Service is unavailable, and stock compensation "
                        "was incomplete. Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=503,
                detail="Product Service is unavailable; reserved stock was released"
            )
        
        if response.status_code != 200:
            released = compensate(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Product Service request failed, and stock compensation "
                        "was incomplete. Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=502,
                detail="Product Service request failed; reserved stock was released"
            )

        try:
            product = response.json()
        except (ValueError, AttributeError):
            released = compensate(reserved_items)
            if not released:
                raise HTTPException(
                    status_code=500,
                    detail="Product response was unreadable and stock compensation was incomplete. Manual reconciliation is required.",
                )
            raise HTTPException(
                status_code=502,
                detail="Product Service returned an unreadable response; reserved stock was released",
            )

        if isinstance(product, dict) and "error" in product:
            released = compensate(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Product not found, and stock compensation was "
                        "incomplete. Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=404,
                detail=f"Product {item.product_id} not found; reserved stock was released"
            )
        
        if not isinstance(product, list) or len(product) < 4:
            released = compensate(reserved_items)
            if not released:
                raise HTTPException(
                    status_code=500,
                    detail="Product response was invalid and stock compensation was incomplete. Manual reconciliation is required.",
                )
            raise HTTPException(
                status_code=502,
                detail="Product Service returned an invalid product response; reserved stock was released",
            )

        if item.quantity <= 0:
            released = compensate(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Invalid quantity, and stock compensation was "
                        "incomplete. Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=400,
                detail="Quantity must be greater than zero; reserved stock was released"
            )

        reservation_record = reservation_records[item_index]
        reservation_id = reservation_record["reservation_id"]
        uncertain_reservation = {
            "product_id": item.product_id,
            "quantity": item.quantity,
            "reservation_id": reservation_id,
            "reservation_index": item_index,
        }
        set_reservation_state(
            idempotency_id,
            reservation_records,
            item_index,
            "RESERVING",
            operation_state,
        )

        try:
            reserve_response = httpx.post(
                f"http://127.0.0.1:8001/products/{item.product_id}/reserve",
                params={
                    "quantity": item.quantity,
                    "reservation_id": reservation_id,
                    "fencing_generation": 0,
                },
                headers=product_service_headers(),
                timeout=5.0
            )
        except httpx.TimeoutException:
            reservation_status = get_product_reservation_status(uncertain_reservation)
            if reservation_status in ("RESERVED", "RELEASED"):
                set_reservation_state(
                    idempotency_id,
                    reservation_records,
                    item_index,
                    reservation_status,
                    operation_state,
                )
            else:
                set_reservation_state(
                    idempotency_id,
                    reservation_records,
                    item_index,
                    "UNKNOWN",
                    operation_state,
                )
            compensation_items = [*reserved_items]
            if reservation_status != "RELEASED":
                compensation_items.append(uncertain_reservation)
            released = compensate(compensation_items)
            if not released:
                raise HTTPException(
                    status_code=500,
                    detail="Reservation outcome is uncertain, and compensation was incomplete. Manual reconciliation is required.",
                )
            raise HTTPException(
                status_code=504,
                detail="Product Service timed out; reservation status was checked and compensation completed",
            )
        except httpx.RequestError:
            reservation_status = get_product_reservation_status(uncertain_reservation)
            if reservation_status in ("RESERVED", "RELEASED"):
                set_reservation_state(
                    idempotency_id,
                    reservation_records,
                    item_index,
                    reservation_status,
                    operation_state,
                )
            else:
                set_reservation_state(
                    idempotency_id,
                    reservation_records,
                    item_index,
                    "UNKNOWN",
                    operation_state,
                )
            compensation_items = [*reserved_items]
            if reservation_status != "RELEASED":
                compensation_items.append(uncertain_reservation)
            released = compensate(compensation_items)
            if not released:
                raise HTTPException(
                    status_code=500,
                    detail="Product Service is unavailable during stock reservation, and compensation was incomplete. Manual reconciliation is required.",
                )
            raise HTTPException(
                status_code=503,
                detail="Product Service is unavailable during stock reservation; compensation completed",
            )

        if reserve_response.status_code == 409:
            try:
                detail = reserve_response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            if detail == "Insufficient stock":
                set_reservation_state(
                    idempotency_id,
                    reservation_records,
                    item_index,
                    "NOT_RESERVED",
                    operation_state,
                )
                released = compensate(reserved_items)
                if not released:
                    raise HTTPException(
                        status_code=500,
                        detail="Stock reservation failed, and compensation was incomplete. Manual reconciliation is required.",
                    )
                raise HTTPException(
                    status_code=409,
                    detail=f"Insufficient stock for product {item.product_id}",
                )

        if reserve_response.status_code == 404:
            reservation_status = get_product_reservation_status(uncertain_reservation)
            if reservation_status == "MISSING":
                reservation_state = "NOT_RESERVED"
            elif reservation_status in ("RESERVED", "RELEASED"):
                reservation_state = reservation_status
            else:
                reservation_state = "UNKNOWN"
            set_reservation_state(
                idempotency_id,
                reservation_records,
                item_index,
                reservation_state,
                operation_state,
            )

            compensation_items = [*reserved_items]
            if reservation_status in ("RESERVED", "UNKNOWN"):
                compensation_items.append(uncertain_reservation)
            released = compensate(compensation_items)
            if not released:
                raise HTTPException(
                    status_code=500,
                    detail="Product was not found during reservation, and compensation was incomplete. Manual reconciliation is required.",
                )
            raise HTTPException(
                status_code=404,
                detail=f"Product {item.product_id} not found",
            )

        reservation_response_valid = False
        if reserve_response.status_code == 200:
            try:
                reservation_response = reserve_response.json()
                reservation_response_valid = (
                    isinstance(reservation_response, dict)
                    and reservation_response.get("reservation_id") == reservation_id
                    and reservation_response.get("product_id") == item.product_id
                )
            except (ValueError, AttributeError):
                reservation_response_valid = False

        if reservation_response_valid:
            set_reservation_state(
                idempotency_id,
                reservation_records,
                item_index,
                "RESERVED",
                operation_state,
            )
        else:
            reservation_status = get_product_reservation_status(uncertain_reservation)
            if reservation_status in ("RESERVED", "RELEASED"):
                set_reservation_state(
                    idempotency_id,
                    reservation_records,
                    item_index,
                    reservation_status,
                    operation_state,
                )
            else:
                set_reservation_state(
                    idempotency_id,
                    reservation_records,
                    item_index,
                    "UNKNOWN",
                    operation_state,
                )
            compensation_items = [*reserved_items]
            if reservation_status != "RELEASED":
                compensation_items.append(uncertain_reservation)
            released = compensate(compensation_items)
            if not released:
                raise HTTPException(
                    status_code=500,
                    detail="Stock reservation outcome is uncertain, and compensation was incomplete. Manual reconciliation is required.",
                )
            raise HTTPException(
                status_code=502,
                detail="Stock reservation failed; reservation status was checked and compensation completed",
            )

        reserved_items.append({
            "product_id": item.product_id,
            "quantity": item.quantity,
            "reservation_id": reservation_id,
            "reservation_index": item_index,
        })

        price = float(product[3])
        total_amount += price * item.quantity

        validated_items.append({
            "product_id": item.product_id,
            "quantity": item.quantity,
            "price": price
        })

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO orders (user_id, total_amount)
                    VALUES (%s, %s)
                    RETURNING id, user_id, total_amount, status, created_at;
                    """,
                    (order.user_id, total_amount)
                )
                new_order = cursor.fetchone()

                for item in validated_items:
                    cursor.execute(
                        """
                        INSERT INTO order_items
                        (order_id, product_id, quantity, price)
                        VALUES (%s, %s, %s, %s);
                        """,
                        (
                            new_order[0],
                            item["product_id"],
                            item["quantity"],
                            item["price"]
                        )
                    )

                response_body = {
                    "id": new_order[0],
                    "user_id": new_order[1],
                    "total_amount": float(new_order[2]),
                    "status": new_order[3],
                    "items": validated_items,
                }
                completed_records = [
                    {**record, "state": "COMMITTED"}
                    for record in reservation_records
                ]
                cursor.execute(
                    """
                    UPDATE order_idempotency
                    SET reservation_ids = %s, order_id = %s, state = 'COMPLETED', response_status = 200,
                        response_body = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND state = 'IN_PROGRESS';
                    """,
                    (Jsonb(completed_records), new_order[0], Jsonb(response_body), idempotency_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Idempotency record was not in progress")
    
    except Exception as error:
        print(f"Order database transaction failed: {error}")

        try:
            outcome, saved_status, saved_body = read_idempotency_outcome(idempotency_id)
        except Exception:
            outcome, saved_status, saved_body = "UNKNOWN", None, None

        if outcome == "COMPLETED":
            return JSONResponse(status_code=saved_status, content=saved_body)

        if outcome != "NOT_COMMITTED":
            try:
                mark_recovery_required(idempotency_id)
            except Exception:
                print("WARNING: Could not mark the order for recovery after a database error")
            operation_state["tracking_failed"] = True
            raise HTTPException(
                status_code=500,
                detail="Order database outcome is uncertain; manual recovery is required",
            )

        released = compensate(reserved_items)

        if not released:
            print(
                "CRITICAL: Some stock reservations may remain active. "
                "Manual reconciliation is required."
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Order creation failed, and stock compensation "
                    "was incomplete. Manual reconciliation is required."
                )
            )

        raise HTTPException(
            status_code=500,
            detail="Order creation failed; reserved stock was released"
        )

    return response_body

@app.get("/orders/{order_id}")
def get_order(
    order_id: int,
    identity: dict = Depends(get_existing_user_identity),
):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, total_amount, status, created_at
                FROM orders
                WHERE id = %s AND user_id = %s;
                """,
                (order_id, identity["user_id"])
            )
            order = cursor.fetchone()

            if order is None:
                raise HTTPException(
                    status_code=404,
                    detail="Order not found"
                )

            cursor.execute(
                """
                SELECT product_id, quantity, price
                FROM order_items
                WHERE order_id = %s;
                """,
                (order_id,)
            )
            items = cursor.fetchall()

    return {
        "id": order[0],
        "user_id": order[1],
        "total_amount": float(order[2]),
        "status": order[3],
        "created_at": order[4],
        "items": [
            {
                "product_id": item[0],
                "quantity": item[1],
                "price": float(item[2])
            }
            for item in items
        ]
    }

@app.get("/orders")
def get_orders(identity: dict = Depends(get_existing_user_identity)):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, total_amount, status, created_at
                FROM orders
                WHERE user_id = %s
                ORDER BY id;
                """,
                (identity["user_id"],),
            )
            orders = cursor.fetchall()

            result = []

            for order in orders:
                cursor.execute(
                    """
                    SELECT product_id, quantity, price
                    FROM order_items
                    WHERE order_id = %s;
                    """,
                    (order[0],)
                )
                items = cursor.fetchall()

                result.append({
                    "id": order[0],
                    "user_id": order[1],
                    "total_amount": float(order[2]),
                    "status": order[3],
                    "created_at": order[4],
                    "items": [
                        {
                            "product_id": item[0],
                            "quantity": item[1],
                            "price": float(item[2])
                        }
                        for item in items
                    ]
                })

    return result
