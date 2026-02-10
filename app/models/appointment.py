import uuid, enum
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base

class AppointmentStatus(str, enum.Enum):
    requested = "requested"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"

class AppointmentType(str, enum.Enum):
    client_meeting = "client_meeting"
    court = "court"
    internal = "internal"
    personal = "personal"

class RequestedBy(str, enum.Enum):
    client = "client"
    lawyer = "lawyer"   # future use


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
        index=True,
    )

    case_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cases.id"),
        nullable=True,
    )

    title = Column(String, nullable=False)
    notes = Column(Text, nullable=True)

    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False)

    type = Column(
        Enum(AppointmentType),
        nullable=False,
        default=AppointmentType.client_meeting,
    )

    status = Column(
        Enum(AppointmentStatus),
        nullable=False,
        default=AppointmentStatus.requested,
    )

    requested_by = Column(
        Enum(RequestedBy),
        nullable=False,
        default=RequestedBy.client,
    )

    client_name = Column(String, nullable=False)
    client_email = Column(String, nullable=False, index=True)
    client_phone = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    workspace = relationship("Workspace")
    case = relationship("Case", back_populates="appointments")