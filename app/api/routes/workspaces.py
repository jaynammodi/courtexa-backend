from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from app.api import deps
from app.models.user import User
from app.models.workspace import Workspace
from app.models.membership import WorkspaceMember, WorkspaceRole
from app.schemas import workspace as workspace_schemas

router = APIRouter()

@router.post("/", response_model=workspace_schemas.Workspace)
def create_workspace(
    *,
    db: Session = Depends(deps.get_db),
    workspace_in: workspace_schemas.WorkspaceCreate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Create new workspace. 
    The creating user becomes the owner and gets the LAWYER role.
    """
    # Check if slug exists
    existing_slug = db.query(Workspace).filter(Workspace.slug == workspace_in.slug).first()
    if existing_slug:
        raise HTTPException(
            status_code=400,
            detail="Workspace with this slug already exists.",
        )
        
    workspace = Workspace(
        name=workspace_in.name,
        slug=workspace_in.slug,
        owner_id=current_user.id
    )
    db.add(workspace)
    db.flush() # Flush to get ID

    # Add owner as member with LAWYER role
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=current_user.id,
        role=WorkspaceRole.LAWYER
    )
    db.add(member)
    db.commit()
    db.refresh(workspace)
    return workspace

@router.get("/me", response_model=workspace_schemas.Workspace)
def get_my_workspace(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    ws = db.query(Workspace).filter(
        Workspace.owner_id == current_user.id
    ).first()

    if not ws:
        raise HTTPException(404, "Workspace not found")

    return ws

@router.get("/by-slug/{slug}")
def get_by_slug(slug: str, db: Session = Depends(deps.get_db)):
    ws = db.query(Workspace).filter(Workspace.slug == slug).first()
    return ws
    
@router.get("/", response_model=List[workspace_schemas.Workspace])
def read_workspaces(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve workspaces that the current user is a member of.
    """
    memberships = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == current_user.id).all()
    workspace_ids = [m.workspace_id for m in memberships]
    
    workspaces = db.query(Workspace).filter(Workspace.id.in_(workspace_ids)).offset(skip).limit(limit).all()
    return workspaces

@router.get("/{workspace_id}", response_model=workspace_schemas.Workspace)
def read_workspace(
    *,
    workspace_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    # Dependency ensures user is a member
    current_member: WorkspaceMember = Depends(deps.WorkspaceAccess()), 
) -> Any:
    """
    Get workspace details.
    """
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    return workspace

@router.post("/{workspace_id}/invite", response_model=workspace_schemas.WorkspaceMember)
def invite_member(
    *,
    workspace_id: uuid.UUID,
    invite_in: workspace_schemas.InviteMember,
    db: Session = Depends(deps.get_db),
    # Only LAWYER can invite
    current_member: WorkspaceMember = Depends(deps.WorkspaceAccess(required_role=WorkspaceRole.LAWYER)),
) -> Any:
    """
    Invite a user to the workspace.
    """
    # Check if user exists
    user = db.query(User).filter(User.email == invite_in.email).first()
    if not user:
         # In a real app we might invite by email (create placeholder), but for now require existing user
         # Or create user with temp password. The requirements said "create user if needed".
         # Let's create a user with a random password if not exists? 
         # Or simpler: require user to exist for MVP, or create disabled user.
         # Requirement: "invite staff (create user if needed)"
         
         password = security.get_password_hash(str(uuid.uuid4())) # Random password
         user = User(
             email=invite_in.email,
             full_name="Invited User",
             password_hash=password, # User will need to reset or is created active?
             is_active=True # Let's assume active
         )
         db.add(user)
         db.flush()

    # Check if already a member
    existing_member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user.id
    ).first()
    if existing_member:
        raise HTTPException(status_code=400, detail="User is already a member of this workspace")

    member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=user.id,
        role=invite_in.role
    )
    db.add(member)
    db.commit()
    db.refresh(member)

from app.schemas.case import HearingResponse

@router.get("/{workspace_id}/hearings", response_model=List[HearingResponse])
def get_workspace_hearings(
    workspace_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_member: WorkspaceMember = Depends(deps.WorkspaceAccess()),
):
    """
    Get all upcoming hearings for the workspace.
    """
    from app.models.case import Case, CaseHistory

    # Query CaseHistory joined with Case
    # Filter by workspace_id and hearing_date is not null
    results = (
        db.query(CaseHistory, Case)
        .join(Case, CaseHistory.case_id == Case.id)
        .filter(
            Case.workspace_id == workspace_id,
            CaseHistory.hearing_date.isnot(None)
        )
        .all()
    )

    hearings = []
    for h, c in results:
        hearings.append({
            "id": h.id,
            "case_id": c.id,
            "hearing_date": h.hearing_date,
            "purpose": h.purpose,
            "judge": h.judge,
            "notes": h.notes,
            
            # Summary fields
            "cino": c.cino,
            "petitioner": c.summary_petitioner,
            "respondent": c.summary_respondent,
            "case_type": c.case_type,
            "court": c.court_name,
            
            "internal_status": c.internal_status,
            "next_hearing_date": c.next_hearing_date, 
        })
    
    # Sort by hearing date
    hearings.sort(key=lambda x: x["hearing_date"])
    
    return hearings

