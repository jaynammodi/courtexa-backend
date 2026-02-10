from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import date, datetime

class CasePartySchema(BaseModel):
    is_petitioner: bool
    name: str # The user wants strict structure, but eCourts gives us a blob. We'll store the blob in name or split if possible.
    advocate: Optional[str] = None
    role: Optional[str] = None
    raw_text: Optional[str] = None

class CaseActSchema(BaseModel):
    act_name: str
    section: Optional[str] = None
    act_code: Optional[str] = None

class CaseHistorySchema(BaseModel):
    business_date: Optional[date] = None
    hearing_date: Optional[date] = None
    purpose: Optional[str] = None
    stage: Optional[str] = None
    notes: Optional[str] = None # For business_update
    judge: Optional[str] = None
    source: str = "scrape"

class CaseOrderSchema(BaseModel):
    order_no: Optional[str] = None
    date: Optional[str] = None
    details: Optional[str] = None
    pdf_link: Optional[str] = None # URL to serve PDF content
    pdf_filename: Optional[str] = None

class CaseCourtSchema(BaseModel):
    name: Optional[str] = None
    level: Optional[str] = None
    bench: Optional[str] = None
    court_code: Optional[str] = None

class CaseSummarySchema(BaseModel):
    petitioner: Optional[str] = None
    respondent: Optional[str] = None
    short_title: Optional[str] = None

class CaseDetailsSchema(BaseModel):
    case_type: Optional[str] = None
    filing_number: Optional[str] = None
    filing_date: Optional[date] = None
    registration_number: Optional[str] = None
    registration_date: Optional[date] = None

class CaseStatusSchema(BaseModel):
    first_hearing_date: Optional[date] = None
    next_hearing_date: Optional[date] = None
    last_hearing_date: Optional[date] = None
    decision_date: Optional[date] = None
    case_stage: Optional[str] = None
    case_status_text: Optional[str] = None
    judge: Optional[str] = None

class CaseFIRSchema(BaseModel):
    police_station: Optional[str] = None
    fir_number: Optional[str] = None
    year: Optional[str] = None

class CaseSchema(BaseModel):
    cino: str
    title: str = "Unknown Case"
    internal_status: str = "active"
    
    court: CaseCourtSchema = Field(default_factory=CaseCourtSchema)
    summary: CaseSummarySchema = Field(default_factory=CaseSummarySchema)
    case_details: CaseDetailsSchema = Field(default_factory=CaseDetailsSchema)
    status: CaseStatusSchema = Field(default_factory=CaseStatusSchema)
    fir_details: Optional[CaseFIRSchema] = Field(default=None)
    
    parties: List[CasePartySchema] = []
    acts: List[CaseActSchema] = []
    history: List[CaseHistorySchema] = []
    orders: List[CaseOrderSchema] = []
    
    meta_scraped_at: datetime = Field(default_factory=datetime.utcnow)
    meta_source: str = "ecourts"
    meta_source_url: Optional[str] = None
    raw_html: Optional[str] = None
