import uuid
from fastapi import APIRouter
from app.redis import create_session, get_session, update_session

router = APIRouter()

@router.post("/start")
def start_session():
    session_id = str(uuid.uuid4())
    create_session(session_id, {
        "id": session_id,
        "step": "INIT",
        "payload": {}
    })
    return {"session_id": session_id}

@router.get("/{session_id}")
def session_status(session_id: str):
    session = get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    return session