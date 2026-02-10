from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import deps
from app.models.availability import WorkspaceAvailability
from app.models.workspace import Workspace
from app.models.appointment import Appointment
from app.schemas.availability import AvailabilityOut


router = APIRouter()


@router.get("/public/{slug}")
def get_public_availability(
    slug: str,
    db: Session = Depends(deps.get_db),
):
    workspace = db.query(Workspace).filter(
        Workspace.slug == slug
    ).first()

    if not workspace:
        raise HTTPException(404, "Workspace not found")

    availability = db.query(WorkspaceAvailability).filter(
        WorkspaceAvailability.workspace_id == workspace.id
    ).first()

    if not availability:
        raise HTTPException(404, "Availability not configured")

    # only return safe appointment data
    appointments = db.query(Appointment).filter(
        Appointment.workspace_id == workspace.id
    ).all()

    return {
        "id": availability.id,
        "workspace_id": workspace.id,
        "workspace_name": workspace.name,
        "workspace_slug": workspace.slug,
        "slot_minutes": availability.slot_minutes,
        "buffer_minutes": availability.buffer_minutes,
        "weekly": availability.weekly,
        "blackout_dates": availability.blackout_dates,
        "appointments": [
            {
                "id": a.id,
                "start_at": a.start_at,
                "end_at": a.end_at,
                "status": a.status,
            }
            for a in appointments
            if a.status != "cancelled"
        ],
    }
