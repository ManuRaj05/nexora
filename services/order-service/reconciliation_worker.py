import time
import os
import httpx
from database import get_connection

PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")


def product_service_headers():
    service_token = os.getenv("ORDER_SERVICE_TOKEN")
    if not service_token or not service_token.strip():
        raise RuntimeError("Order Service authentication is not configured")
    return {"X-Order-Service-Token": service_token}

def claim_task():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reconciliation_tasks
                SET status = 'PENDING',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'PROCESSING'
                  AND updated_at < CURRENT_TIMESTAMP - INTERVAL '2 minutes';
                """
            )

            cursor.execute(
                """
                SELECT id, reservation_id, product_id, quantity, action, attempts
                FROM reconciliation_tasks
                WHERE status = 'PENDING'
                  AND next_retry_at <= CURRENT_TIMESTAMP
                ORDER BY id
                FOR UPDATE SKIP LOCKED
                LIMIT 1;
                """
            )

            task = cursor.fetchone()

            if task is None:
                return None

            cursor.execute(
                """
                UPDATE reconciliation_tasks
                SET status = 'PROCESSING',
                    attempts = attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (task[0],)
            )

            return task

def schedule_retry(task_id, attempts, error):
    delay = min(5 * (2 ** max(attempts - 1, 0)), 300)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reconciliation_tasks
                SET status = 'PENDING',
                    next_retry_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                    last_error = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (delay, str(error)[:2000], task_id)
            )

    print(f"Task {task_id} scheduled to retry in {delay} seconds")

def process_task(task):
    task_id, reservation_id, product_id, quantity, action, attempts = task

    if action != "RELEASE":
        schedule_retry(task_id, attempts, f"Unsupported action: {action}")
        return

    try:
        headers = product_service_headers()
    except RuntimeError as error:
        schedule_retry(task_id, attempts, error)
        return

    try:
        response = httpx.post(
            f"{PRODUCT_SERVICE_URL}/products/{product_id}/release",
            params={
                "quantity": quantity,
                "reservation_id": str(reservation_id),
                "fencing_generation": 0,
            },
            headers=headers,
            timeout=5.0
        )

        if (
            response.status_code == 200
            and response.json().get("status") == "RELEASED"
        ):            
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE reconciliation_tasks
                        SET status = 'COMPLETED',
                            last_error = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s;
                        """,
                        (task_id,)
                    )

            print(f"Task {task_id} completed successfully")
            return

        schedule_retry(
            task_id,
            attempts,
            f"Product Service returned HTTP {response.status_code}: {response.text}"
        )

    except httpx.RequestError as error:
        schedule_retry(task_id, attempts, error)

def main():
    print("Nexora Reconciliation Worker started")

    while True:
        try:
            task = claim_task()

            if task:
                process_task(task)
            else:
                time.sleep(2)

        except Exception as error:
            print(f"Worker error: {error}")
            time.sleep(2)


if __name__ == "__main__":
    main()
