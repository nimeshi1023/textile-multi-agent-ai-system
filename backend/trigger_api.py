import httpx

try:
    response = httpx.post("http://localhost:8000/production/analyze", json={"order_id": "ORD-2026-0007"}, timeout=10.0)
    print("STATUS:", response.status_code)
    print("RESPONSE:", response.text)
except Exception as e:
    print("ERROR:", e)
