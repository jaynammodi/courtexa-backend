from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base
import uuid
from datetime import datetime

class WorkspaceMultiSaveJob(Base):
    __tablename__ = "workspace_multi_save_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"))

    total_cases = Column(Integer, nullable=False)
    completed_cases = Column(Integer, default=0)
    failed_cases = Column(Integer, default=0)

    status = Column(String, default="running")  # running | completed | aborted

    created_at = Column(DateTime, default=datetime.utcnow)
