from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import uuid

from app.api import deps
from app.models.appointment import Appointment, AppointmentStatus, AppointmentType, RequestedBy
from app.models.workspace import Workspace
from app.models.membership import WorkspaceMember
from app.schemas import appointment as appointment_schemas
from app.models.user import User

router = APIRouter()

@router.post("", response_model=appointment_schemas.Appointment)
def create_appointment_request(
    *,
    db: Session = Depends(deps.get_db),
    appointment_in: appointment_schemas.AppointmentCreate,
    workspace_id: uuid.UUID = Query(...),
) -> Any:

    workspace = db.query(Workspace).filter(
        Workspace.id == workspace_id
    ).first()

    if not workspace:
        raise HTTPException(404, "Workspace not found")

    # ✅ generate title server-side
    title = f"{workspace.name} × {appointment_in.client_name}"

    appointment = Appointment(
        workspace_id=workspace_id,
        case_id=appointment_in.case_id,
        notes=appointment_in.notes,
        start_at=appointment_in.start_at,
        end_at=appointment_in.end_at,
        client_name=appointment_in.client_name,
        client_email=appointment_in.client_email,
        client_phone=appointment_in.client_phone,

        title=title,
        type=AppointmentType.client_meeting,
        status=AppointmentStatus.requested,
        requested_by=RequestedBy.client,
    )

    db.add(appointment)
    db.commit()
    db.refresh(appointment)

    return appointment

@router.get("", response_model=List[appointment_schemas.Appointment])
def read_appointments(
    *,
    db: Session = Depends(deps.get_db),
    workspace_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    List appointments for a workspace.
    Requires membership in that workspace.
    """
    # Check membership manually or use dependency?
    # Since workspace_id is a query param, we can't easily use the deps.WorkspaceAccess class directly as a dependency signature 
    # unless we make a custom dependency that reads the query param.
    # Manual check here:
    
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == current_user.id
    ).first()
    
    if not member or not member.is_active:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    appointments = db.query(Appointment).filter(
        Appointment.workspace_id == workspace_id
    ).offset(skip).limit(limit).all()
    
    return appointments

@router.get("/{id}", response_model=appointment_schemas.Appointment)
def read_appointment(
    *,
    id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get an appointment.
    """
    appointment = db.query(Appointment).filter(Appointment.id == id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    # Check permission
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == appointment.workspace_id,
        WorkspaceMember.user_id == current_user.id
    ).first()
    
    if not member or not member.is_active:
        raise HTTPException(status_code=403, detail="Not authorized")

    return appointment

@router.patch("/{id}/confirm", response_model=appointment_schemas.Appointment)
def confirm_appointment(
    *,
    id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Confirm an appointment.
    """
    appointment = db.query(Appointment).filter(Appointment.id == id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    # Check permission
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == appointment.workspace_id,
        WorkspaceMember.user_id == current_user.id
    ).first()
    
    if not member or not member.is_active:
        raise HTTPException(status_code=403, detail="Not authorized")

    appointment.status = AppointmentStatus.CONFIRMED
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment

@router.patch("/{id}/cancel", response_model=appointment_schemas.Appointment)
def cancel_appointment(
    *,
    id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Cancel an appointment.
    """
    appointment = db.query(Appointment).filter(Appointment.id == id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    # Check permission
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == appointment.workspace_id,
        WorkspaceMember.user_id == current_user.id
    ).first()
    
    if not member or not member.is_active:
        raise HTTPException(status_code=403, detail="Not authorized")

    appointment.status = AppointmentStatus.CANCELLED
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment

@router.patch("/{appointment_id}/status", response_model=appointment_schemas.Appointment)
def update_appointment_status(
    *,
    db: Session = Depends(deps.get_db),
    appointment_id: uuid.UUID,
    status_in: appointment_schemas.AppointmentStatusUpdate,
    current_user: User = Depends(deps.get_current_user),
):
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(404, "Appointment not found")

    appt.status = status_in.status
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt