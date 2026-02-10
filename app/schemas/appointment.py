from pydantic import BaseModel, EmailStr
from datetime import datetime
from uuid import UUID
from typing import Optional

from app.models.appointment import AppointmentStatus, AppointmentType, RequestedBy


class AppointmentCreate(BaseModel):
    start_at: datetime
    end_at: datetime

    client_name: str
    client_email: EmailStr
    client_phone: Optional[str] = None

    notes: Optional[str] = None
    case_id: Optional[UUID] = None

class Appointment(BaseModel):
    id: UUID

    workspace_id: UUID
    case_id: Optional[UUID]

    title: str
    notes: Optional[str]

    start_at: datetime
    end_at: datetime

    type: AppointmentType
    status: AppointmentStatus

    client_name: str
    client_email: EmailStr
    client_phone: Optional[str]

    requested_by: RequestedBy

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatus