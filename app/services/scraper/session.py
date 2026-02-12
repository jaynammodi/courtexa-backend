import json
import uuid
import time
from typing import Dict, Optional, Any
from app.core.redis import get_redis
from app.core.config import settings
from app.services.scraper.errors import SessionExpiredError

# Session States
STATE_INIT = "INIT"
STATE_CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
STATE_CAPTCHA_SUBMITTED = "CAPTCHA_SUBMITTED"
STATE_SEARCH_SUBMITTED = "SEARCH_SUBMITTED"
STATE_CASE_LIST_LOADED = "CASE_LIST_LOADED"
STATE_HISTORY_FETCHED = "HISTORY_FETCHED"
STATE_COMPLETED = "COMPLETED"
STATE_FAILED = "FAILED"

class ScraperSession:
    def __init__(self, session_id: str, data: Dict[str, Any]):
        self.session_id = session_id
        self.data = data
        self.is_dirty = False

    @property
    def search_mode(self) -> str:
        return self.data.get("search_mode", "cnr")

    @property
    def state(self) -> str:
        return self.data.get("state", STATE_INIT)

    @state.setter
    def state(self, value: str):
        self.data["state"] = value
        self.is_dirty = True

    @property
    def cookies(self) -> Dict:
        return self.data.get("cookies", {})

    @cookies.setter
    def cookies(self, value: Dict):
        self.data["cookies"] = value
        self.is_dirty = True

    @property
    def app_token(self) -> Optional[str]:
        return self.data.get("app_token")

    @app_token.setter
    def app_token(self, value: Optional[str]):
        self.data["app_token"] = value
        self.is_dirty = True

    @classmethod
    async def create(cls, search_mode: str, payload: Dict[str, Any] = {}) -> "ScraperSession":
        session_id = str(uuid.uuid4())
        initial_data = {
            "state": STATE_INIT,
            "search_mode": search_mode,
            "payload": payload,
            "app_token": None,
            "cookies": {},
            "retries": 0,
            "last_error": None,
            "created_at": time.time()
        }
        session = cls(session_id, initial_data)
        await session.save()
        return session

    @classmethod
    async def get(cls, session_id: str) -> "ScraperSession":
        redis = await get_redis()
        data_json = await redis.get(f"session:{session_id}")
        if not data_json:
            raise SessionExpiredError(f"Session {session_id} not found or expired.")
        return cls(session_id, json.loads(data_json))

    async def save(self):
        try:
            redis = await get_redis()
            await redis.setex(
                f"session:{self.session_id}", 
                settings.SESSION_TTL, 
                json.dumps(self.data)
            )
            self.is_dirty = False
        except Exception as e:
            raise e

    async def delete(self):
        redis = await get_redis()
        await redis.delete(f"session:{self.session_id}")

    def update_payload(self, updates: Dict[str, Any]):
        self.data["payload"].update(updates)
        self.is_dirty = True

    def set_error(self, error_msg: str):
        self.data["last_error"] = str(error_msg)
        self.state = STATE_FAILED
        self.is_dirty = True

    def increment_retry(self):
        self.data["retries"] = self.data.get("retries", 0) + 1
        self.is_dirty = True

    def reset_retry(self):
        self.data["retries"] = 0
        self.is_dirty = True
