"""Minimal FastAPI app for integration testing."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/users")
def users():
    return {"users": []}
