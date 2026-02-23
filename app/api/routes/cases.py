from rich.pretty import pprint
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Response
from sqlalchemy.orm import Session
from uuid import UUID
from app.db.session import SessionLocal

from app.api import deps
from app.api.deps import get_db
from app.models.case import Case, CaseParty, CaseHistory, CaseAct, CaseOrder
from app.models.workspace import Workspace
from app.models.user import User
from app.schemas.case import Case as CaseSchema, CaseCreate, CaseUpdate, HearingResponse, CaseIndexRow, CaseSummaryDTO
from app.services.scraper.flows import refresh_case
from app.models.workspace_refresh_job import WorkspaceRefreshJob
from datetime import datetime, timedelta
from app.services.storage import get_storage
from sqlalchemy import or_
from datetime import datetime, timedelta, date

JOB_TIMEOUT_MINUTES = 15

router = APIRouter()

import asyncio
import os

MAX_REFRESH_WORKERS = int(os.getenv("MAX_REFRESH_WORKERS", 8))


async def perform_full_case_refresh(case_id: UUID, job_id: UUID | None = None):
    db = SessionLocal()
    print("Running background refresh for", case_id)
    job = None

    try:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            return

        if job_id:
            job = db.query(WorkspaceRefreshJob).filter(
                WorkspaceRefreshJob.id == job_id
            ).first()
            
        case.sync_status = "in_progress"
        db.commit()

        result = await refresh_case(case.cino, max_retries=5)

        if not result or not result.get("data"):
            case.sync_status = "error"
            case.sync_error_message = "Failed to refresh"
            
            if job:
                db.query(WorkspaceRefreshJob).filter(
                    WorkspaceRefreshJob.id == job.id
                ).update({
                    WorkspaceRefreshJob.failed_cases:
                        WorkspaceRefreshJob.failed_cases + 1
                })

            db.commit()
            return

        data = result["data"]["structured_data"]

        # ---- FULL UPDATE (same as your single case) ----
        case.internal_status = data["internal_status"]
        case.title = data["title"]

        case.court_name = data["court"]["name"]
        case.court_level = data["court"]["level"]
        case.court_bench = data["court"]["bench"]
        case.court_code = data["court"]["court_code"]

        case.summary_petitioner = data["summary"]["petitioner"]
        case.summary_respondent = data["summary"]["respondent"]
        case.summary_short_title = data["summary"]["short_title"]

        case.case_type = data["case_details"]["case_type"]
        case.filing_number = data["case_details"]["filing_number"]
        case.filing_date = data["case_details"]["filing_date"]
        case.registration_number = data["case_details"]["registration_number"]
        case.registration_date = data["case_details"]["registration_date"]

        case.first_hearing_date = data["status"]["first_hearing_date"]
        case.next_hearing_date = data["status"]["next_hearing_date"]
        case.last_hearing_date = data["status"]["last_hearing_date"]
        case.decision_date = data["status"]["decision_date"]
        case.case_stage = data["status"]["case_stage"]
        case.case_status_text = data["status"]["case_status_text"]
        case.judge = data["status"]["judge"]

        case.meta_scraped_at = data["meta_scraped_at"]
        case.meta_source_url = data["meta_source_url"]
        case.raw_html = data["raw_html"]

        case.sync_last_synced_at = data["meta_scraped_at"]
        case.sync_status = "fresh"
        case.sync_error_message = None

        # ---- WIPE CHILDREN ----
        db.query(CaseParty).filter(CaseParty.case_id == case.id).delete()
        db.query(CaseAct).filter(CaseAct.case_id == case.id).delete()
        db.query(CaseHistory).filter(CaseHistory.case_id == case.id).delete()
        # db.query(CaseOrder).filter(CaseOrder.case_id == case.id).delete()
        
        # ---- CLEAN OLD ORDERS + FILES ----
        old_orders = db.query(CaseOrder).filter(
            CaseOrder.case_id == case.id
        ).all()

        storage = get_storage()

        for order in old_orders:
            if order.file_path:
                try:
                    await storage.delete(order.file_path)
                except Exception as e:
                    print("Failed to delete old PDF:", order.file_path, e)

        # Now delete DB rows
        db.query(CaseOrder).filter(
            CaseOrder.case_id == case.id
        ).delete()

        for p in data["parties"]:
            db.add(CaseParty(
                case_id=case.id,
                is_petitioner=p["is_petitioner"],
                name=p["name"],
                advocate=p["advocate"],
                role=p["role"],
                raw_text=p["raw_text"]
            ))

        for a in data["acts"]:
            db.add(CaseAct(
                case_id=case.id,
                act_name=a["act_name"],
                section=a["section"],
                act_code=a["act_code"]
            ))

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

        for o in data.get("orders", []):
            db.add(CaseOrder(
                case_id=case.id,
                order_no=o.get("order_no"),
                order_date=o.get("order_date"),
                details=o.get("details"),
                pdf_filename=o.get("pdf_filename"),
                file_path=o.get("file_path"),
            ))

        if job:
            db.query(WorkspaceRefreshJob).filter(
                WorkspaceRefreshJob.id == job.id
            ).update({
                WorkspaceRefreshJob.completed_cases:
                    WorkspaceRefreshJob.completed_cases + 1
            })

            updated_job = db.query(WorkspaceRefreshJob).filter(
                WorkspaceRefreshJob.id == job.id
            ).first()

            if updated_job.completed_cases + updated_job.failed_cases >= updated_job.total_cases:
                updated_job.status = "completed"

        # SINGLE COMMIT
        db.commit()
        print("Refreshed case", case_id)

    except Exception:
        db.rollback()

        case = db.query(Case).filter(Case.id == case_id).first()
        if case:
            case.sync_status = "error"
            case.sync_error_message = "Background refresh failed"

        if job_id:
            job = db.query(WorkspaceRefreshJob).filter(
                WorkspaceRefreshJob.id == job_id
            ).first()
            if job:
                db.query(WorkspaceRefreshJob).filter(
                    WorkspaceRefreshJob.id == job.id
                ).update({
                    WorkspaceRefreshJob.failed_cases:
                        WorkspaceRefreshJob.failed_cases + 1
                })

                # 🔥 ADD COMPLETION CHECK
                updated_job = db.query(WorkspaceRefreshJob).filter(
                    WorkspaceRefreshJob.id == job.id
                ).first()

                if updated_job.completed_cases + updated_job.failed_cases >= updated_job.total_cases:
                    updated_job.status = "completed"

        db.commit()

    finally:
        db.close()


@router.get("/", response_model=List[CaseIndexRow])
def read_cases(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(deps.get_current_workspace),
    skip: int = 0,
    limit: int = 100,
    search: str = Query(None)
) -> Any:
    """
    Retrieve cases involved in the current workspace.
    """
    # Verify workspace membership
    # For now, simplistic approach: check if user is in workspace (logic to be added in deps or service)
    # Assuming user has access if they possess the workspace_id for this MVP
    
    query = db.query(Case).filter(Case.workspace_id == workspace.id)
    
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
    workspace: Workspace = Depends(deps.get_current_workspace),
) -> Any:
    """
    Create new case.
    """
    existing = db.query(Case).filter(
        Case.workspace_id == workspace.id,
        Case.cino == case_in.cino
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Case already exists in this workspace")
    
    case = Case(
        cino=case_in.cino,
        title=case_in.title,
        workspace_id=workspace.id,
        internal_status="active"
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case

@router.post("/refresh-all", status_code=202)
def refresh_all_cases(
    *,
    workspace: Workspace = Depends(deps.get_current_workspace),
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # cases = db.query(Case).filter(
    #     Case.workspace_id == workspace.id,
    #     Case.internal_status == "active"
    # ).all()
    now = datetime.utcnow()
    twelve_hours_ago = now - timedelta(hours=12)
    today = date.today()

    cases = db.query(Case).filter(
        Case.workspace_id == workspace.id,
        Case.internal_status == "active",

        # Not refreshed in last 12 hours
        or_(
            Case.sync_last_synced_at == None,
            Case.sync_last_synced_at < twelve_hours_ago
        ),

        # Only cases whose next hearing is today or earlier
        Case.next_hearing_date != None,
        Case.next_hearing_date <= today
    ).all()

    if not cases:
        return {"status": "no_cases"}

    # 1️⃣ Create job
    job = WorkspaceRefreshJob(
        workspace_id=workspace.id,
        total_cases=len(cases),
        completed_cases=0,
        failed_cases=0,
        status="running"
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    # 2️⃣ Queue background tasks
    for case in cases:
        case.sync_status = "queued"

        background_tasks.add_task(
            perform_full_case_refresh,
            case.id,
            job.id
        )

    db.commit()

    return {
        "job_id": job.id,
        "total": job.total_cases,
        "status": job.status
    }

@router.get("/refresh-jobs/{job_id}")
def get_refresh_job_status(
    *,
    job_id: UUID,
    workspace: Workspace = Depends(deps.get_current_workspace),
    db: Session = Depends(get_db),
):
    job = db.query(WorkspaceRefreshJob).filter(
        WorkspaceRefreshJob.id == job_id,
        WorkspaceRefreshJob.workspace_id == workspace.id
    ).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "total": job.total_cases,
        "completed": job.completed_cases,
        "failed": job.failed_cases,
        "status": job.status
    }

@router.get("/refresh-active")
def get_active_refresh_job(
    workspace: Workspace = Depends(deps.get_current_workspace),
    db: Session = Depends(get_db),
):
    job = db.query(WorkspaceRefreshJob).filter(
        WorkspaceRefreshJob.workspace_id == workspace.id,
        WorkspaceRefreshJob.status == "running"
    ).order_by(WorkspaceRefreshJob.created_at.desc()).first()

    if not job:
        return Response(status_code=204)

    return {
        "job_id": job.id,
        "total": job.total_cases,
        "completed": job.completed_cases,
        "failed": job.failed_cases,
        "status": job.status
    }

@router.get("/{id}", response_model=CaseSchema)
def read_case(
    *,
    db: Session = Depends(get_db),
    id: UUID,
    workspace: Workspace = Depends(deps.get_current_workspace),
) -> Any:
    """
    Get case by ID.
    """
    case = db.query(Case).filter(Case.id == id, Case.workspace_id == workspace.id).first()
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
    workspace: Workspace = Depends(deps.get_current_workspace),
) -> Any:
    """
    Update a case.
    """
    case = db.query(Case).filter(Case.id == id, Case.workspace_id == workspace.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Update logic (skipped for brewity as per instructions)
    db.commit()
    db.refresh(case)
    return case

@router.post("/{id}/refresh", status_code=202)
def refresh_case_data(
    *,
    id: UUID,
    workspace: Workspace = Depends(deps.get_current_workspace),
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    case = db.query(Case).filter(
        Case.id == id,
        Case.workspace_id == workspace.id
    ).first()

    print(" [] REFRESHING CASE {} ".format(id))
    pprint(case)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")


    case.sync_status = "queued"
    db.commit()

    background_tasks.add_task(perform_full_case_refresh, case.id)

    return {"status": "queued"}

@router.delete("/{id}", status_code=204)
async def delete_case(
    *,
    db: Session = Depends(get_db),
    id: UUID,
    workspace: Workspace = Depends(deps.get_current_workspace),
) -> None:
    """
    Delete a case belonging to the current workspace.
    """

    case = db.query(Case).filter(
        Case.id == id,
        Case.workspace_id == workspace.id
    ).first()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        # Fetch orders first
        orders = db.query(CaseOrder).filter(
            CaseOrder.case_id == case.id
        ).all()

        storage = get_storage()

        for order in orders:
            if order.file_path:
                try:
                    await storage.delete(order.file_path)
                except Exception as e:
                    print("Failed to delete PDF:", order.file_path, e)

        db.delete(case)
        db.commit()

    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete case")

@router.get("/{case_id}/orders/{order_id}/pdf")
async def get_case_order_pdf(
    case_id: UUID,
    order_id: UUID,
    workspace: Workspace = Depends(deps.get_current_workspace),
    db: Session = Depends(get_db),
):
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.workspace_id == workspace.id
    ).first()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    order = db.query(CaseOrder).filter(
        CaseOrder.id == order_id,
        CaseOrder.case_id == case.id
    ).first()

    if not order or not order.file_path:
        raise HTTPException(status_code=404, detail="PDF not found")

    storage = get_storage()
    pdf_bytes = await storage.read(order.file_path)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{order.pdf_filename}"'
        }
    )

