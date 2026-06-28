from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any

from core.instances import odysseus as odysseus_svc

router = APIRouter(prefix="/odysseus", tags=["odysseus"])


@router.get("/status")
async def odysseus_status() -> dict[str, Any]:
    """Check if Odysseus is reachable at the configured URL."""
    connected = await odysseus_svc.check_connectivity()
    return {
        "connected": connected,
        "url": odysseus_svc.base_url,
        "mode": "live" if connected else "offline",
    }


class ResearchRequest(BaseModel):
    query: str


@router.post("/research/start")
async def start_research(body: ResearchRequest) -> dict[str, Any]:
    """
    Start a Deep Research session in Odysseus with the given query.
    Returns the session_id and Odysseus URL so the frontend can open it.
    """
    return await odysseus_svc.start_research(body.query)


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


@router.post("/chat")
async def send_chat(body: ChatRequest) -> dict[str, Any]:
    """Send a message to Odysseus chat (optionally continuing a session)."""
    return await odysseus_svc.send_chat(body.message, body.session_id)
