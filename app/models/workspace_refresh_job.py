import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base_class import Base


class WorkspaceRefreshJob(Base):
    __tablename__ = "workspace_refresh_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)

    total_cases = Column(Integer, nullable=False)
    completed_cases = Column(Integer, default=0)
    failed_cases = Column(Integer, default=0)

    status = Column(String, default="queued")  # queued | running | completed | aborted

    created_at = Column(DateTime, default=datetime.utcnow)