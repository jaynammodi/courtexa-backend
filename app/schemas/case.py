from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# --- Nested Components ---

class CaseIndexRow(BaseModel):
    id: UUID
    cino: str
    title: str
    internal_status: str

    case_type: Optional[str]
    court_name: Optional[str]
    judge: Optional[str]

    petitioner: Optional[str]
    respondent: Optional[str]

    index_next_hearing_date: Optional[date]
    filing_number: Optional[str]
    registration_number: Optional[str]

    priority: Optional[str]
    starred: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

class CaseSummaryDTO(BaseModel):
    id: UUID
    cino: str
    title: str

    petitioner: Optional[str]
    respondent: Optional[str]

    case_type: Optional[str]
    court: Optional[str]
    judge: Optional[str]

    internal_status: str
    next_hearing_date: Optional[date]

    class Config:
        from_attributes = True

class CourtInfo(BaseModel):
    name: Optional[str] = None
    level: Optional[str] = None
    bench: Optional[str] = None
    court_code: Optional[str] = None

class CaseSummary(BaseModel):
    petitioner: Optional[str] = None
    respondent: Optional[str] = None
    shortTitle: Optional[str] = None

class CaseDetails(BaseModel):
    case_type: Optional[str] = None
    filing_number: Optional[str] = None
    filing_date: Optional[date] = None
    registration_number: Optional[str] = None
    registration_date: Optional[date] = None

class CaseStatus(BaseModel):
    first_hearing_date: Optional[date] = None
    next_hearing_date: Optional[date] = None
    last_hearing_date: Optional[date] = None
    decision_date: Optional[date] = None
    case_stage: Optional[str] = None
    case_status_text: Optional[str] = None
    nature_of_disposal: Optional[str] = None
    judge: Optional[str] = None

class CaseUserMeta(BaseModel):
    priority: Optional[str] = None
    starred: bool = False
    color: Optional[str] = None
    tags: List[str] = []

class CaseSync(BaseModel):
    last_synced_at: Optional[datetime] = None
    status: str = "never"
    error_message: Optional[str] = None

class CaseMeta(BaseModel):
    scraped_at: Optional[datetime] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    raw_html: Optional[str] = None

class CaseLinks(BaseModel):
    appointment_ids: Optional[List[str]] = None
    document_ids: Optional[List[str]] = None

# --- Related Entities ---

class CasePartySchema(BaseModel):
    id: UUID
    is_petitioner: bool
    name: str
    advocate: Optional[str] = None
    role: Optional[str] = None
    raw_text: Optional[str] = None

    class Config:
        from_attributes = True

class CaseActSchema(BaseModel):
    id: UUID
    act_name: str
    section: Optional[str] = None
    act_code: Optional[str] = None

    class Config:
        from_attributes = True

class CaseHistorySchema(BaseModel):
    id: UUID
    business_date: Optional[date] = None
    hearing_date: Optional[date] = None
    purpose: Optional[str] = None
    stage: Optional[str] = None
    notes: Optional[str] = None
    judge: Optional[str] = None
    source: Optional[str] = None

    class Config:
        from_attributes = True

class CaseOrderSchema(BaseModel):
    id: UUID
    order_no: Optional[str] = None
    order_date: Optional[date] = None
    details: Optional[str] = None
    pdf_filename: Optional[str] = None
    file_path: Optional[str] = None

    class Config:
        from_attributes = True

class HearingResponse(BaseModel):
    id: UUID
    case_id: UUID
    hearing_date: date
    purpose: Optional[str] = None
    judge: Optional[str] = None
    notes: Optional[str] = None
    
    # Case Summary Fields
    cino: Optional[str] = None
    petitioner: Optional[str] = None
    respondent: Optional[str] = None
    case_type: Optional[str] = None
    court: Optional[str] = None
    
    internal_status: Optional[str] = None
    next_hearing_date: Optional[date] = None

    class Config:
        from_attributes = True

class CasePartiesUnified(BaseModel):
    petitioners: List[CasePartySchema] = []
    respondents: List[CasePartySchema] = []

# --- Main Case Schema ---

class CaseBase(BaseModel):
    cino: str
    title: str
    internal_status: str

    court: CourtInfo
    summary: CaseSummary
    case_details: CaseDetails
    status: CaseStatus
    user_meta: CaseUserMeta
    sync: CaseSync
    meta: CaseMeta

class Case(CaseBase):
    id: UUID  # Pydantic will cast UUID to str automatically
    workspace_id: UUID

    parties: CasePartiesUnified
    acts: List[CaseActSchema] = []
    history: List[CaseHistorySchema] = []
    orders: List[CaseOrderSchema] = []

    links: Optional[CaseLinks] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Write Schemas (Simplification) ---

# For creating a case we might accept nested flat structures or the full tree. 
# For now, let's keep it simple or align it with the seeding script requirements.
# The seed script creates DB models directly, so CaseCreate might not be strictly needed right now unless we build the POST API immediately.
# Let's verify with a simple generic Create schema.

class CaseCreate(BaseModel):
    cino: str
    title: str
    
    # We can accept flat fields here for easier API creation, or nested.
    # Given the complexity, let's just use the DB model kwargs approach for now in api logic.
    pass

class CaseUpdate(BaseModel):
    pass
