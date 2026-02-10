import uuid
from sqlalchemy import Column, Integer, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class WorkspaceAvailability(Base):
    __tablename__ = "workspace_availability"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    slot_minutes = Column(Integer, nullable=False, default=30)
    buffer_minutes = Column(Integer, nullable=False, default=10)

    weekly = Column(JSON, nullable=False)         # your weekly array
    blackout_dates = Column(JSON, nullable=False) # ["YYYY-MM-DD"]

    workspace = relationship("Workspace")