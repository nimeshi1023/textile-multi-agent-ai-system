import httpx
from typing import Any

API_URL = "http://localhost:8000"

def analyze_message(text: str) -> dict[str, Any]:
    response = httpx.post(f"{API_URL}/orders/analyze/message", json={"text": text}, timeout=None)
    response.raise_for_status()
    return response.json()

def analyze_pdf(file_bytes: bytes, filename: str) -> dict[str, Any]:
    files = {"file": (filename, file_bytes, "application/pdf")}
    response = httpx.post(f"{API_URL}/orders/analyze/pdf", files=files, timeout=None)
    response.raise_for_status()
    return response.json()

def create_order(order_data: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(f"{API_URL}/orders", json=order_data, timeout=30.0)
    response.raise_for_status()
    return response.json()

def get_orders(priority: str = None) -> list[dict[str, Any]]:
    params = {}
    if priority and priority != "All":
        params["priority"] = priority
    response = httpx.get(f"{API_URL}/orders", params=params, timeout=30.0)
    response.raise_for_status()
    return response.json()

def delete_order(cus_ord_id: str) -> None:
    response = httpx.delete(f"{API_URL}/orders/{cus_ord_id}", timeout=30.0)
    response.raise_for_status()

def analyze_resources(request_data: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(f"{API_URL}/production/analyze", json=request_data, timeout=None)
    response.raise_for_status()
    return response.json()