from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class StartCaseRequest(BaseModel):
    search_mode: str = "cnr" # cnr, party, advocate
    cnr: Optional[str] = None
    
    # Party Search Fields
    party_name: Optional[str] = None
    registration_year: Optional[str] = None
    case_status: Optional[str] = None # Pending, Disposed, Both
    
    # Advocate Search Fields
    advocate_name: Optional[str] = None
    
    # Location (Required for Party/Advocate)
    state_code: Optional[str] = None
    dist_code: Optional[str] = None
    court_complex_code: Optional[str] = None
    
class SelectCaseRequest(BaseModel):
    case_index: int

class CaptchaSubmitRequest(BaseModel):
    captcha: str

class SessionStatusResponse(BaseModel):
    session_id: str
    state: str
    retries: int
    last_error: Optional[str] = None

class CaseResultResponse(BaseModel):
    session_id: str
    state: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class MultiSelectRequest(BaseModel):
    case_indices: List[int]

class MultiSaveRequest(BaseModel):
    case_indices: List[int]
