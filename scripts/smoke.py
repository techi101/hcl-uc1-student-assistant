"""Quick end-to-end smoke test of the API skeleton (no server needed)."""
# WHAT THIS FILE IS: a 10-second check that the API starts and answers, without starting a server.
# It calls /health, asks one policy question, and sends an empty question (expected 422 = rejected by input validation).
# Real example output: "health: {'api': 'ok', ...}", then "ask: 200 {...}", then "empty question -> 422".
# TestClient = FastAPI's fake browser: it calls the API inside this Python process.
from fastapi.testclient import TestClient

from app.main import app

# One fake client, then GET /health: is every component up?
c = TestClient(app)
print("health:", c.get("/health").json())
# One real /ask call: status code + the full JSON answer.
r = c.post("/ask", json={"question": "What is the minimum attendance?", "as_of_date": "2026-10-06"})
print("ask:", r.status_code, r.json())
# An empty question must be refused by validation (422), never sent to the graph.
print("empty question ->", c.post("/ask", json={"question": ""}).status_code)
