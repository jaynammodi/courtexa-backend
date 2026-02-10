from typing import Generator, Optional
from fastapi import Depends, HTTPException, status, Request, Header
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User

from app.schemas.auth import TokenPayload
from app.models.membership import WorkspaceMember, WorkspaceRole
from app.models.workspace import Workspace

def get_db() -> Generator:
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:

    token = None

    # 1️⃣ Try Authorization header
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    # 2️⃣ Fallback to cookie
    if not token:
        token = request.cookies.get("cx_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        token_data = TokenPayload(**payload)

    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    user = db.query(User).filter(User.id == token_data.sub).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user

def get_current_workspace(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Workspace:

    ws = db.query(Workspace).filter(
        Workspace.owner_id == current_user.id
    ).first()

    if not ws:
        raise HTTPException(404, "Workspace not found")

    return ws

def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

def get_current_active_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=400, detail="The user doesn't have enough privileges"
        )
    return current_user

# Workspace Dependencies

class WorkspaceAccess:
    def __init__(self, required_role: Optional[WorkspaceRole] = None):
        self.required_role = required_role

    def __call__(
        self, 
        workspace_id: str, 
        current_user: User = Depends(get_current_active_user),
        db: Session = Depends(get_db)
    ) -> WorkspaceMember:
        member = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id
        ).first()

        if not member:
            raise HTTPException(
                status_code=403, detail="You are not a member of this workspace"
            )
        
        if not member.is_active:
             raise HTTPException(
                status_code=403, detail="Your membership is inactive"
            )

        if self.required_role:
             if self.required_role == WorkspaceRole.LAWYER and member.role != WorkspaceRole.LAWYER:
                  raise HTTPException(
                    status_code=403, detail="Insufficient permissions (Lawyer role required)"
                )
        
        return member
