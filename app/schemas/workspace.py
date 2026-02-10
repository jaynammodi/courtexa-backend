import uuid
from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from app.models.membership import WorkspaceRole

class WorkspaceBase(BaseModel):
    name: str
    slug: str

class WorkspaceCreate(WorkspaceBase):
    pass

class Workspace(WorkspaceBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True

class WorkspaceMemberBase(BaseModel):
    user_id: uuid.UUID
    role: WorkspaceRole
    is_active: bool

class WorkspaceMember(WorkspaceMemberBase):
    id: uuid.UUID
    workspace_id: uuid.UUID
    joined_at: datetime

    class Config:
        from_attributes = True

class InviteMember(BaseModel):
    email: str
    role: WorkspaceRole = WorkspaceRole.STAFF
