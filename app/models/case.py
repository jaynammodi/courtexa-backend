import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Date, Text, ARRAY, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base

class Case(Base):
    __tablename__ = "cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)

    cino = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    internal_status = Column(String, default="active", nullable=False) # active, disposed, archived

    # --- Court Info ---
    court_name = Column(String, nullable=True)
    court_level = Column(String, nullable=True)
    court_bench = Column(String, nullable=True)
    court_code = Column(String, nullable=True)

    # --- Summary ---
    summary_petitioner = Column(String, nullable=True)
    summary_respondent = Column(String, nullable=True)
    summary_short_title = Column(String, nullable=True)

    # --- Case Details ---
    case_type = Column(String, nullable=True)
    filing_number = Column(String, nullable=True)
    filing_date = Column(Date, nullable=True)
    registration_number = Column(String, nullable=True)
    registration_date = Column(Date, nullable=True)

    # --- Status ---
    first_hearing_date = Column(Date, nullable=True)
    next_hearing_date = Column(Date, nullable=True)
    last_hearing_date = Column(Date, nullable=True)
    decision_date = Column(Date, nullable=True)
    
    case_stage = Column(String, nullable=True)
    case_status_text = Column(String, nullable=True)
    nature_of_disposal = Column(String, nullable=True)
    judge = Column(String, nullable=True)

    # --- User Meta ---
    priority = Column(String, nullable=True) # low, medium, high
    starred = Column(Boolean, default=False)
    color = Column(String, nullable=True)
    tags = Column(ARRAY(String), default=[])

    # --- Sync ---
    sync_last_synced_at = Column(DateTime, nullable=True)
    sync_status = Column(String, default="never") # fresh, stale, error, never
    sync_error_message = Column(Text, nullable=True)

    # --- Meta ---
    meta_scraped_at = Column(DateTime, nullable=True)
    meta_source = Column(String, nullable=True)
    meta_source_url = Column(String, nullable=True)
    raw_html = Column(Text, nullable=True)

    # --- Timestamps ---
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    workspace = relationship("Workspace")
    
    # One-to-Many
    # Rename to _parties so we can expose a structured "parties" property
    _parties = relationship("CaseParty", back_populates="case", cascade="all, delete-orphan")
    acts = relationship("CaseAct", back_populates="case", cascade="all, delete-orphan")
    history = relationship("CaseHistory", back_populates="case", cascade="all, delete-orphan")
    orders = relationship("CaseOrder", back_populates="case", cascade="all, delete-orphan")
    
    # Relation back from appointments
    appointments = relationship("Appointment", back_populates="case")

    @property
    def parties(self):
        # Sort _parties into petitioners and respondents
        petitioners = [p for p in self._parties if p.is_petitioner]
        respondents = [p for p in self._parties if not p.is_petitioner]
        return {
            "petitioners": petitioners,
            "respondents": respondents,
        }

    def _format_party_list(self, parties, limit: int = 2) -> str | None:
        if not parties:
            return None

        names = [p.name for p in parties if p.name]
        if not names:
            return None

        if len(names) <= limit:
            return ", ".join(names)

        return f"{', '.join(names[:limit])} et al"

    @property
    def petitioner(self):
        petitioners = [p for p in self._parties if p.is_petitioner]
        return self._format_party_list(petitioners)

    @property
    def respondent(self):
        respondents = [p for p in self._parties if not p.is_petitioner]
        return self._format_party_list(respondents)

    @property
    def index_next_hearing_date(self):
        return self.next_hearing_date

    @property
    def links(self):
        return {
            "appointment_ids": [str(a.id) for a in self.appointments] if self.appointments else [],
            "document_ids": [] # Placeholder
        }

    # --- Properties for Pydantic Serialization ---
    @property
    def court(self):
        return {
            "name": self.court_name,
            "level": self.court_level,
            "bench": self.court_bench,
            "court_code": self.court_code,
        }

    @property
    def summary(self):
        return {
            "petitioner": self.summary_petitioner,
            "respondent": self.summary_respondent,
            "shortTitle": self.summary_short_title,
        }

    @property
    def case_details(self):
        return {
            "case_type": self.case_type,
            "filing_number": self.filing_number,
            "filing_date": self.filing_date,
            "registration_number": self.registration_number,
            "registration_date": self.registration_date,
        }

    @property
    def status(self):
        return {
            "first_hearing_date": self.first_hearing_date,
            "next_hearing_date": self.next_hearing_date,
            "last_hearing_date": self.last_hearing_date,
            "decision_date": self.decision_date,
            "case_stage": self.case_stage,
            "case_status_text": self.case_status_text,
            "judge": self.judge,
        }

    @property
    def user_meta(self):
        return {
            "priority": self.priority,
            "starred": self.starred,
            "color": self.color,
            "tags": self.tags,
        }

    @property
    def sync(self):
        return {
            "last_synced_at": self.sync_last_synced_at,
            "status": self.sync_status,
            "error_message": self.sync_error_message,
        }

    @property
    def meta(self):
        return {
            "scraped_at": self.meta_scraped_at,
            "source": self.meta_source,
            "source_url": self.meta_source_url,
            "raw_html": self.raw_html,
        }


class CaseParty(Base):
    __tablename__ = "case_parties"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False, index=True)

    is_petitioner = Column(Boolean, nullable=False, default=True) # True = Petitioner, False = Respondent
    name = Column(String, nullable=False)
    advocate = Column(String, nullable=True)
    role = Column(String, nullable=True)
    raw_text = Column(String, nullable=True)
    
    case = relationship("Case", back_populates="_parties")


class CaseAct(Base):
    __tablename__ = "case_acts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False, index=True)

    act_name = Column(String, nullable=False)
    section = Column(String, nullable=True) # e.g. "302, 34"
   
    act_code = Column(String, nullable=True)

    case = relationship("Case", back_populates="acts")

    @property
    def sections(self):
        return [s.strip() for s in self.section.split(",")] if self.section else []

class CaseHistory(Base):
    __tablename__ = "case_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False, index=True)

    business_date = Column(Date, nullable=True)
    hearing_date = Column(Date, nullable=True)
    
    purpose = Column(String, nullable=True)
    stage = Column(String, nullable=True)
    
    notes = Column(Text, nullable=True)
    judge = Column(String, nullable=True)
    source = Column(String, default="scrape") # scrape | manual

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    case = relationship("Case", back_populates="history")


class CaseOrder(Base):
    __tablename__ = "case_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False, index=True)

    order_no = Column(String, nullable=True)
    order_date = Column(Date, nullable=True)
    order_details = Column(Text, nullable=True)
    
    pdf_filename = Column(String, nullable=True) # stored filename
    file_path = Column(String, nullable=True)  # full storage path
    file_size = Column(Integer, nullable=True) # file size in bytes
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    case = relationship("Case", back_populates="orders")
