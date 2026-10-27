from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
import httpx
import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"), override=False)

app = FastAPI(title="Nexora API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
)

class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str

class ProductCreate(BaseModel):
    name: str
    description: str
    price: float
    stock: int
    category: str

class ProductUpdate(BaseModel):
    name: str
    description: str
    price: float
    stock: int
    category: str

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int


class OrderCreate(BaseModel):
    user_id: int
    items: List[OrderItemCreate]
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://127.0.0.1:8000").rstrip("/")
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://127.0.0.1:8002").rstrip("/")

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
async def register_user(user: UserCreate):
    return await forward_request(
        "POST",
        f"{USER_SERVICE_URL}/users/register",
        "User Service",
        json_data=user.model_dump()
    )

@app.post("/users/login")
async def login_user(user: UserLogin):
    return await forward_request(
        "POST",
        f"{USER_SERVICE_URL}/users/login",
        "User Service",
        json_data=user.model_dump()
    )

@app.get("/products")
async def get_products():
    return await forward_request(
        "GET",
        f"{PRODUCT_SERVICE_URL}/products",
        "Product Service"
    )
    
@app.post("/products")
async def create_product(product: ProductCreate, request: Request):
    authorization = request.headers.get("Authorization")
    return await forward_request(
        "POST",
        f"{PRODUCT_SERVICE_URL}/products",
        "Product Service",
        json_data=product.model_dump(),
        headers={"Authorization": authorization} if authorization else None,
    )


@app.put("/products/{product_id}")
async def update_product(product_id: int, product: ProductUpdate, request: Request):
    authorization = request.headers.get("Authorization")
    return await forward_request(
        "PUT",
        f"{PRODUCT_SERVICE_URL}/products/{product_id}",
        "Product Service",
        json_data=product.model_dump(),
        headers={"Authorization": authorization} if authorization else None,
    )


@app.delete("/products/{product_id}")
async def delete_product(product_id: int, request: Request):
    authorization = request.headers.get("Authorization")
    return await forward_request(
        "DELETE",
        f"{PRODUCT_SERVICE_URL}/products/{product_id}",
        "Product Service",
        headers={"Authorization": authorization} if authorization else None,
    )

@app.get("/products/{product_id}")
async def get_product(product_id: int):
    return await forward_request(
        "GET",
        f"{PRODUCT_SERVICE_URL}/products/{product_id}",
        "Product Service"
    )

@app.get("/orders")
async def get_orders(request: Request):
    authorization = request.headers.get("Authorization")
    return await forward_request(
        "GET",
        f"{ORDER_SERVICE_URL}/orders",
        "Order Service",
        headers={"Authorization": authorization} if authorization else None,
        timeout=10.0
    )

@app.get("/orders/{order_id}")
async def get_order(order_id: int, request: Request):
    authorization = request.headers.get("Authorization")
    return await forward_request(
        "GET",
        f"{ORDER_SERVICE_URL}/orders/{order_id}",
        "Order Service",
        headers={"Authorization": authorization} if authorization else None,
        timeout=10.0
    )

@app.post("/orders")
async def create_order(order: OrderCreate, request: Request):
    authorization = request.headers.get("Authorization")
    idempotency_key = request.headers.get("Idempotency-Key")
    headers = {}
    if authorization:
        headers["Authorization"] = authorization
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return await forward_request(
        "POST",
        f"{ORDER_SERVICE_URL}/orders",
        "Order Service",
        json_data=order.model_dump(),
        headers=headers or None,
        timeout=30.0
    )
