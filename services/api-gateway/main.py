from fastapi import FastAPI, HTTPException, Request
import httpx

app = FastAPI(title="Nexora API Gateway")

USER_SERVICE_URL = "http://127.0.0.1:8000"
PRODUCT_SERVICE_URL = "http://127.0.0.1:8001"
ORDER_SERVICE_URL = "http://127.0.0.1:8002"

async def forward_request(
    method: str,
    url: str,
    service_name: str,
    json_data: dict | None = None,
    headers: dict | None = None,
    timeout: float = 5.0
):
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                json=json_data,
                headers=headers
            )

        if response.status_code >= 400:
            try:
                error_detail = response.json().get(
                    "detail", response.text
                )
            except (ValueError, AttributeError):
                error_detail = response.text

            raise HTTPException(
                status_code=response.status_code,
                detail=error_detail
            )

        return response.json()

    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail=f"{service_name} unavailable"
        )

@app.get("/health")
def health():
    return {"status": "healthy", "service": "api-gateway"}

@app.get("/users/me")
async def get_current_user(request: Request):
    authorization = request.headers.get("Authorization")

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header missing"
        )

    return await forward_request(
        "GET",
        f"{USER_SERVICE_URL}/users/me",
        "User Service",
        headers={"Authorization": authorization}
    )

@app.post("/users/register")
async def register_user(user: dict):
    return await forward_request(
        "POST",
        f"{USER_SERVICE_URL}/users/register",
        "User Service",
        json_data=user
    )

@app.post("/users/login")
async def login_user(user: dict):
    return await forward_request(
        "POST",
        f"{USER_SERVICE_URL}/users/login",
        "User Service",
        json_data=user
    )

@app.get("/products")
async def get_products():
    return await forward_request(
        "GET",
        f"{PRODUCT_SERVICE_URL}/products",
        "Product Service"
    )
    
@app.get("/products/{product_id}")
async def get_product(product_id: int):
    return await forward_request(
        "GET",
        f"{PRODUCT_SERVICE_URL}/products/{product_id}",
        "Product Service"
    )

@app.get("/orders")
async def get_orders():
    return await forward_request(
        "GET",
        f"{ORDER_SERVICE_URL}/orders",
        "Order Service",
        timeout=10.0
    )

@app.get("/orders/{order_id}")
async def get_order(order_id: int):
    return await forward_request(
        "GET",
        f"{ORDER_SERVICE_URL}/orders/{order_id}",
        "Order Service",
        timeout=10.0
    )

@app.post("/orders")
async def create_order(order: dict):
    return await forward_request(
        "POST",
        f"{ORDER_SERVICE_URL}/orders",
        "Order Service",
        json_data=order,
        timeout=30.0
    )
