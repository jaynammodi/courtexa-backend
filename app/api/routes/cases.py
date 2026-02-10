from typing import List, Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.models.case import Case
from app.schemas.case import Case as CaseSchema, CaseIndexRow, CaseSummaryDTO
from app.db.session import SessionLocal
from app.models.membership import WorkspaceMember

router = APIRouter()

@router.get("", response_model=List[CaseIndexRow])
def list_cases(
    workspace_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    limit: int = 100,
    skip: int = 0,
) -> Any:
    """
    Retrieve cases for the current user's workspace(s).
    For now, we fetch all cases in workspaces the user belongs to.
    """
    # Only get cases for the current user's workspace

    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    cases = (
        db.query(Case)
        .filter(Case.workspace_id == workspace_id)
        .offset(skip)
        .limit(limit)
        .all()
    )
    return cases

@router.get("/{id}", response_model=CaseSchema)
def get_case(
    id: str, # Accepting string to match frontend expectations, typically UUID or CINO? 
             # Schema says ID is string, Model has UUID. Pydantic handles str->uuid.
             # However, if frontend passes CINO as ID, we might need to handle lookup by CINO too later.
             # For now, assuming ID is the UUID PK.
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get a specific case by ID (UUID).
    """
    try:
        case_uuid = uuid.UUID(id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format"
        )

    case = db.query(Case).filter(Case.id == case_uuid).first()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found"
        )
    
    # Check permission
    # Simplified: User must be member of the workspace the case belongs to.
    # user_workspace_ids = [m.workspace_id for m in current_user.workspace_members]
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == case.workspace_id,
        WorkspaceMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    return case


@router.get("/{id}/summary", response_model=CaseSummaryDTO)
def get_case_summary(
    id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    case = db.query(Case).filter(Case.id == id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == case.workspace_id,
        WorkspaceMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return {
        "id": case.id,
        "cino": case.cino,
        "title": case.title,
        "petitioner": case.summary["petitioner"],
        "respondent": case.summary["respondent"],
        "case_type": case.case_type,
        "court": case.court_name,
        "judge": case.judge,
        "internal_status": case.internal_status,
        "next_hearing_date": case.next_hearing_date,
    }