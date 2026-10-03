"""
SENTINEL-X — FastAPI Application Entry Point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel_x.api.routes import router as sessions_router
from sentinel_x.api.websocket import router as ws_router


app = FastAPI(
    title="SENTINEL-X",
    description="Semantic Impact Resolution for Interruptible Real-Time Agents",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(ws_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "sentinel-x"}
