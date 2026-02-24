from datetime import timedelta, datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api import deps
from app.core import security
from app.core.config import settings
from app.models.user import User
from app.models.workspace import Workspace
from app.models.membership import WorkspaceMember, WorkspaceRole
from app.schemas import auth as auth_schemas
from app.schemas import user as user_schemas
from slugify import slugify
import uuid


router = APIRouter()

@router.post("/register", response_model=user_schemas.User)
def register(
    user_in: auth_schemas.UserRegister,
    db: Session = Depends(deps.get_db),
) -> Any:
    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="A user with this email already exists.",
        )
    user = User(
        email=user_in.email,
        password_hash=security.get_password_hash(user_in.password),
        full_name=user_in.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)


    base_slug = slugify(user.full_name)
    unique_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    # ✅ auto create workspace
    workspace = Workspace(
        name=f"{user.full_name}'s Workspace",
        owner_id=user.id,
        slug=unique_slug,
    )

    db.add(workspace)
    db.commit()

    workspace_member = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role=WorkspaceRole.LAWYER,
        is_active=True,
        joined_at=datetime.utcnow(),
    )

    db.add(workspace_member)
    db.commit()

    return user


@router.post("/login", response_model=auth_schemas.Token)
def login_access_token(
    response: Response,
    db: Session = Depends(deps.get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    user = db.query(User).filter(User.email == form_data.username).first()

    if not user or not security.verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token_expires = timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

    token = security.create_access_token(
        user.id,
        expires_delta=access_token_expires
    )

    # ✅ SET HTTPONLY COOKIE
    response.set_cookie(
        key="cx_token",
        value=token,
        httponly=True,
        secure=False,          # keep True in prod (https)
        # secure=True,          # keep True in prod (https)
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )

    return {
        "access_token": token,
        "token_type": "bearer",
    }

@router.get("/me", response_model=user_schemas.User)
def read_users_me(
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    return current_user

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key="cx_token",
        path="/",
    )
    return {"message": "Logged out"}