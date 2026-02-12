from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.api import deps
from app.api.deps import get_db
from app.models.case import Case, CaseParty, CaseHistory, CaseAct
from app.models.user import User
from app.schemas.case import Case as CaseSchema, CaseCreate, CaseUpdate, HearingResponse, CaseIndexRow, CaseSummaryDTO
from app.services.scraper.flows import refresh_case

router = APIRouter()

@router.get("/", response_model=List[CaseIndexRow])
def read_cases(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
    workspace_id: UUID = Query(...),
    search: str = Query(None)
) -> Any:
    """
    Retrieve cases involved in the current workspace.
    """
    # Verify workspace membership
    # For now, simplistic approach: check if user is in workspace (logic to be added in deps or service)
    # Assuming user has access if they possess the workspace_id for this MVP
    
    query = db.query(Case).filter(Case.workspace_id == workspace_id)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Case.title.ilike(search_term)) | 
            (Case.cino.ilike(search_term))
        )
        
    cases = query.offset(skip).limit(limit).all()
    return cases

@router.post("/", response_model=CaseSchema)
def create_case(
    *,
    db: Session = Depends(get_db),
    case_in: CaseCreate,
    current_user: User = Depends(deps.get_current_active_user),
    workspace_id: UUID = Query(...)
) -> Any:
    """
    Create new case.
    """
    case = Case(
        cino=case_in.cino,
        title=case_in.title,
        workspace_id=workspace_id,
        internal_status="active"
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case

@router.get("/{id}", response_model=CaseSchema)
def read_case(
    *,
    db: Session = Depends(get_db),
    id: UUID,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get case by ID.
    """
    case = db.query(Case).filter(Case.id == id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    # Verify access logic here
    return case

@router.put("/{id}", response_model=CaseSchema)
def update_case(
    *,
    db: Session = Depends(get_db),
    id: UUID,
    case_in: CaseUpdate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Update a case.
    """
    case = db.query(Case).filter(Case.id == id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Update logic (skipped for brewity as per instructions)
    db.commit()
    db.refresh(case)
    return case

@router.post("/{id}/refresh", response_model=CaseSchema)
async def refresh_case_data(
    *,
    db: Session = Depends(get_db),
    id: UUID,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Triggers an automated scrape to refresh the case data.
    """
    case = db.query(Case).filter(Case.id == id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        # 1. Trigger Refresh Flow
        result = await refresh_case(case.cino, max_retries=5)
        
        if not result or not result.get("data"):
             raise HTTPException(status_code=500, detail="Failed to refresh case data after multiple retries")
        
        data = result["data"]["structured_data"]
        
        # 2. Update Case Fields
        case.internal_status = data["internal_status"]
        case.title = data["title"] # In case it changed?
        
        # Court
        case.court_name = data["court"]["name"]
        case.court_level = data["court"]["level"]
        case.court_bench = data["court"]["bench"]
        case.court_code = data["court"]["court_code"]
        
        # Summary
        case.summary_petitioner = data["summary"]["petitioner"]
        case.summary_respondent = data["summary"]["respondent"]
        case.summary_short_title = data["summary"]["short_title"]
        
        # Details
        case.case_type = data["case_details"]["case_type"]
        case.filing_number = data["case_details"]["filing_number"]
        case.filing_date = data["case_details"]["filing_date"]
        case.registration_number = data["case_details"]["registration_number"]
        case.registration_date = data["case_details"]["registration_date"]
        
        # Status
        case.first_hearing_date = data["status"]["first_hearing_date"]
        case.next_hearing_date = data["status"]["next_hearing_date"]
        case.last_hearing_date = data["status"]["last_hearing_date"]
        case.decision_date = data["status"]["decision_date"]
        case.case_stage = data["status"]["case_stage"]
        case.case_status_text = data["status"]["case_status_text"]
        case.judge = data["status"]["judge"]
        
        # Meta
        case.meta_scraped_at = data["meta_scraped_at"]
        case.meta_source_url = data["meta_source_url"]
        case.raw_html = data["raw_html"]
        
        case.sync_last_synced_at = data["meta_scraped_at"]
        case.sync_status = "fresh"
        case.sync_error_message = None
        
        # 3. Update Related (Strategy: Wipe and Replace for simplicity, or upsert?)
        # For MVP, wipe and replace is safer to ensure no stale checks remain.
        # But we must be careful with IDs if frontend relies on them efficiently.
        # Since we just refresh, new IDs are acceptable for sub-entities.
        
        # Clear existing
        db.query(CaseParty).filter(CaseParty.case_id == case.id).delete()
        db.query(CaseAct).filter(CaseAct.case_id == case.id).delete()
        db.query(CaseHistory).filter(CaseHistory.case_id == case.id).delete()
        
        # Add new Parties
        for p in data["parties"]:
            db.add(CaseParty(
                case_id=case.id,
                is_petitioner=p["is_petitioner"],
                name=p["name"],
                advocate=p["advocate"],
                role=p["role"],
                raw_text=p["raw_text"]
            ))
            
        # Add new Acts
        for a in data["acts"]:
            db.add(CaseAct(
                case_id=case.id,
                act_name=a["act_name"],
                section=a["section"],
                act_code=a["act_code"]
            ))
            
        # Add new History
        for h in data["history"]:
            db.add(CaseHistory(
                case_id=case.id,
                business_date=h["business_date"],
                hearing_date=h["hearing_date"],
                purpose=h["purpose"],
                stage=h["stage"],
                notes=h["notes"],
                judge=h["judge"],
                source=h["source"]
            ))
            
        db.commit()
        db.refresh(case)
        return case

    except Exception as e:
        case.sync_status = "error"
        case.sync_error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Refresh failed: {str(e)}")