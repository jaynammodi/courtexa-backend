from pydantic import BaseModel, EmailStr

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenPayload(BaseModel):
    sub: str | None = None
    workspace_id: str | None = None

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
