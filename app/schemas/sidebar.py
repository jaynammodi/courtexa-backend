# app/schemas/sidebar.py

from pydantic import BaseModel

class SidebarInitRequest(BaseModel):
    search_mode: str
    payload: dict


class SidebarInitResponse(BaseModel):
    session_id: str
    captcha_base64: str


class SidebarSubmitRequest(BaseModel):
    session_id: str
    captcha: str
    search_mode: str
    payload: dict