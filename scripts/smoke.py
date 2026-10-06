"""Quick end-to-end smoke test of the API skeleton (no server needed)."""
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
print("health:", c.get("/health").json())
r = c.post("/ask", json={"question": "What is the minimum attendance?", "as_of_date": "2026-10-06"})
print("ask:", r.status_code, r.json())
print("empty question ->", c.post("/ask", json={"question": ""}).status_code)
