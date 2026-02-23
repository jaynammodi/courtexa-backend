from rich.pretty import pprint
from fastapi import APIRouter, HTTPException, Response, Depends, Query
from app.schemas.scraper import StartCaseRequest, CaptchaSubmitRequest, SessionStatusResponse, CaseResultResponse, SelectCaseRequest, MultiSelectRequest, MultiSaveRequest
from app.schemas.sidebar import SidebarInitRequest, SidebarInitResponse, SidebarSubmitRequest
from app.services.scraper.flows import start_session, get_captcha, submit_captcha, fetch_results, get_case_list, select_case
from fastapi.concurrency import run_in_threadpool
from app.services.scraper.session import ScraperSession
from app.services.scraper.errors import ECourtsError
from app.api import deps
from app.models.user import User
from app.models.case import Case, CaseParty, CaseHistory, CaseAct, CaseOrder
from app.api.deps import get_db
from sqlalchemy.orm import Session
from uuid import UUID
from app.services.scraper.client import ECourtsClient
from app.services.scraper.utils import parse_options_html
from app.services.storage import get_storage
from bs4 import BeautifulSoup
import time
import base64

# ---- PLAN LIMITS (backend simulated) ----

class PlanLimits:
    def __init__(self, multi_preview, multi_save, result_window):
        self.multi_preview = multi_preview
        self.multi_save = multi_save
        self.result_window = result_window


PLAN_LIMITS = {
    "free":    PlanLimits(3, 3, 50),
    "starter": PlanLimits(10, 10, 100),
    "pro":     PlanLimits(50, 50, 200),
}

def get_user_plan_limits(user: User) -> PlanLimits:
    # TODO replace with real subscription lookup
    return PLAN_LIMITS["free"]

def build_ecourts_payload(mode: str, p: dict):
    if mode == "party":
        return {
            "petres_name": p.get("party_name"),
            "rgyearP": p.get("registration_year") or "",
            "case_status": p.get("case_status") or "Both",
            "state_code": p.get("state_code"),
            "dist_code": p.get("dist_code"),
            "court_complex_code": p.get("court_complex_code"),
            "est_code": "null"
        }

    if mode == "advocate":
        return {
            "radAdvt": "1",
            "advocate_name": p.get("advocate_name"),
            "case_status": p.get("case_status") or "Both",
            "state_code": p.get("state_code"),
            "dist_code": p.get("dist_code"),
            "court_complex_code": p.get("court_complex_code"),
            "est_code": "null",
            "caselist_date": time.strftime("%d-%m-%Y")
        }

    if mode == "cnr":
        return {
            "cnr": p.get("cnr")
        }

    return p

router = APIRouter()

@router.post("/start", response_model=SessionStatusResponse)
async def start_case(
    request: StartCaseRequest,
    current_user: User = Depends(deps.get_current_active_user)
):
    try:
        payload = {}
        
        if request.search_mode == "cnr":
            if not request.cnr:
                raise HTTPException(status_code=400, detail="CNR is required for CNR search mode")
            payload["cnr"] = request.cnr
            
        elif request.search_mode == "party":
            if not request.party_name or len(request.party_name) < 3:
                raise HTTPException(status_code=400, detail="Party Name (min 3 chars) required")
            if not request.state_code or not request.dist_code or not request.court_complex_code:
                 raise HTTPException(status_code=400, detail="Location details (state, dist, complex) required")
            
            payload.update({
                'petres_name': request.party_name,
                'rgyearP': request.registration_year or '',
                'case_status': request.case_status or 'Both',
                'state_code': request.state_code,
                'dist_code': request.dist_code,
                'court_complex_code': request.court_complex_code,
                'est_code': 'null' 
            })
            
        elif request.search_mode == "advocate":
            if not request.advocate_name or len(request.advocate_name) < 3:
                raise HTTPException(status_code=400, detail="Advocate Name (min 3 chars) required")
            if not request.state_code or not request.dist_code or not request.court_complex_code:
                 raise HTTPException(status_code=400, detail="Location details (state, dist, complex) required")
            
            payload.update({
                'radAdvt': '1', 
                'advocate_name': request.advocate_name, 
                'case_status': request.case_status or 'Both',
                'adv_bar_state': '', 'adv_bar_code': '', 'adv_bar_year': '', 'case_type': '',
                'caselist_date': time.strftime("%d-%m-%Y"),
                'state_code': request.state_code,
                'dist_code': request.dist_code,
                'court_complex_code': request.court_complex_code,
                'est_code': 'null'
            })
        else:
             raise HTTPException(status_code=400, detail="Invalid search_mode")
            
        session_id = await start_session(request.search_mode, payload)
        
        # Get initial state
        session = await ScraperSession.get(session_id)
        return SessionStatusResponse(
            session_id=session.session_id,
            state=session.state,
            retries=session.data.get("retries", 0),
            last_error=session.data.get("last_error")
        )
    except ECourtsError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list/{session_id}")
async def get_cases_list_route(
    session_id: str,
    current_user: User = Depends(deps.get_current_active_user)
):
    try:
        limits = get_user_plan_limits(current_user)

        result = await get_case_list(session_id)
        cases = result.get("cases")
        pprint(cases)

        if not cases:
            return []

        # HARD WINDOW LIMIT
        result["cases"] = cases[: limits.result_window]
        return result

    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/select-case/{session_id}")
async def select_case_endpoint(
    session_id: str, 
    request: SelectCaseRequest,
    current_user: User = Depends(deps.get_current_active_user)
):
    try:
        result = await select_case(session_id, request.case_index)
        return result
    except Exception as e:
        print("DEBUG:", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/select-multiple/{session_id}")
async def select_multiple_cases(
    session_id: str,
    request: MultiSelectRequest,
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    Sequentially selects multiple cases using the same logic as single select.
    No state mutation hacks.
    """

    results = []

    try:
        for index in request.case_indices:
            # Select + fully process one case
            result = await select_case(session_id, index)
            # result = await fetch_results(session_id)

            if result.get("status") != "success":
                raise HTTPException(
                    status_code=400,
                    detail=f"Case at index {index} not fully fetched"
                )

            results.append(result)

            # IMPORTANT:
            # DO NOT manually override session.state
            # select_case should return session naturally
            # to CASE_LIST_LOADED at the end.

        return {"cases": results}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/captcha/{session_id}")
async def get_captcha_image(
    session_id: str,
    current_user: User = Depends(deps.get_current_active_user)
):
    try:
        img_bytes = await get_captcha(session_id)
        return Response(content=img_bytes, media_type="image/png")
    except ECourtsError as e:
         raise HTTPException(status_code=400, detail=str(e))

@router.post("/captcha/{session_id}")
async def submit_captcha_code(
    session_id: str, 
    request: CaptchaSubmitRequest,
    current_user: User = Depends(deps.get_current_active_user)
):
    try:
        await submit_captcha(session_id, request.captcha)
        return {"status": "submitted"}
    except ECourtsError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/status/{session_id}", response_model=SessionStatusResponse)
async def get_status(
    session_id: str,
    current_user: User = Depends(deps.get_current_active_user)
):
    try:
        session = await ScraperSession.get(session_id)
        return SessionStatusResponse(
            session_id=session.session_id,
            state=session.state,
            retries=session.data.get("retries", 0),
            last_error=session.data.get("last_error")
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail="Session not found")

@router.get("/pdf/{session_id}/{filename}")
async def get_case_pdf(
    session_id: str,
    filename: str,
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    Returns stored PDF for a scraped case.
    Frontend-safe.
    """

    try:
        session = await ScraperSession.get(session_id)

        files = session.data.get("files", {})
        stored_path = files.get(filename)

        if not stored_path:
            raise HTTPException(status_code=404, detail="PDF not found")

        storage = get_storage()

        pdf_bytes = await storage.read(stored_path)

        if not pdf_bytes:
            raise HTTPException(status_code=404, detail="PDF file missing")

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"'
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/result/{session_id}", response_model=CaseResultResponse)
async def get_result(
    session_id: str,
    current_user: User = Depends(deps.get_current_active_user)
):
    try:
        result = await fetch_results(session_id)
        return CaseResultResponse(
            session_id=session_id,
            state=result.get("state"),
            data=result.get("data"),
            error=result.get("error")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/meta/states")
async def get_states(
    current_user: User = Depends(deps.get_current_active_user)
):
    """Fetch list of available states from eCourts."""
    try:
        client = ECourtsClient()
        # In threadpool to avoid blocking
        token, home_html = await run_in_threadpool(client.get_initial_token)
        
        if not home_html:
             raise HTTPException(status_code=500, detail="Failed to load eCourts homepage")
        
        soup = BeautifulSoup(home_html, 'html.parser')
        state_select = soup.find('select', id='sess_state_code')
        
        if not state_select:
             raise HTTPException(status_code=500, detail="State dropdown not found")
             
        states = parse_options_html(str(state_select))
        return {"states": states}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/meta/districts/{state_code}")
async def get_districts(
    state_code: str,
    current_user: User = Depends(deps.get_current_active_user)
):
    """Fetch districts for a given state."""
    try:
        client = ECourtsClient()
        await run_in_threadpool(client.get_initial_token) # Init session
        
        resp = await run_in_threadpool(client.get_districts, state_code)
        districts = parse_options_html(resp.text)
        return {"districts": districts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/meta/complexes/{state_code}/{dist_code}")
async def get_complexes(
    state_code: str, 
    dist_code: str,
    current_user: User = Depends(deps.get_current_active_user)
):
    """Fetch court complexes for a given state and district."""
    try:
        client = ECourtsClient()
        await run_in_threadpool(client.get_initial_token) # Init session
        
        resp = await run_in_threadpool(client.get_complexes, state_code, dist_code)
        complexes = parse_options_html(resp.text)
        return {"complexes": complexes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/save/{session_id}")
async def save_case_to_workspace(
    session_id: str,
    workspace_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    Saves the scraped case (from session) to the database under the given workspace.
    """
    try:
        # 1. Fetch Result
        result = await fetch_results(session_id)
        if result.get("state") != "HISTORY_FETCHED" or not result.get("data"):
             raise HTTPException(status_code=400, detail="Scraper session not completed or no data found")
             
        data = result["data"]["structured_data"]
        
        # 2. Check if exists
        cino = data["cino"]
        existing_case = db.query(Case).filter(Case.cino == cino, Case.workspace_id == workspace_id).first()
        if existing_case:
            raise HTTPException(status_code=409, detail=f"Case {cino} already exists in this workspace")

        # 3. Create Case Object
        # Flatten structure to match Case model
        
        # Helper to parse dates safely
        # Pydantic exports dates as strings in JSON mode, so we might need parsing if SQLAlchemy requires date objects
        # But if we pass strings to Date column, SQLAlchemy usually handles it if format is ISO.
        # However, data["status"]["first_hearing_date"] might be YYYY-MM-DD string.
        
        case_obj = Case(
            workspace_id=workspace_id,
            cino=cino,
            title=data["title"],
            internal_status=data["internal_status"],
            
            court_name=data["court"]["name"],
            court_level=data["court"]["level"],
            court_bench=data["court"]["bench"],
            court_code=data["court"]["court_code"],
            
            summary_petitioner=data["summary"]["petitioner"],
            summary_respondent=data["summary"]["respondent"],
            summary_short_title=data["summary"]["short_title"],
            
            case_type=data["case_details"]["case_type"],
            filing_number=data["case_details"]["filing_number"],
            filing_date=data["case_details"]["filing_date"],
            registration_number=data["case_details"]["registration_number"],
            registration_date=data["case_details"]["registration_date"],
            
            first_hearing_date=data["status"]["first_hearing_date"],
            next_hearing_date=data["status"]["next_hearing_date"],
            last_hearing_date=data["status"]["last_hearing_date"],
            decision_date=data["status"]["decision_date"],
            
            case_stage=data["status"]["case_stage"],
            case_status_text=data["status"]["case_status_text"],
            nature_of_disposal=data["status"]["nature_of_disposal"],
            judge=data["status"]["judge"],
            
            # Meta
            meta_scraped_at=data["meta_scraped_at"],
            meta_source=data["meta_source"],
            meta_source_url=data["meta_source_url"],
            raw_html=data["raw_html"]
        )
        
        db.add(case_obj)
        db.flush() # Get ID
        
        # 4. Add Related Entities
        
        # Parties
        for p in data["parties"]:
            db.add(CaseParty(
                case_id=case_obj.id,
                is_petitioner=p["is_petitioner"],
                name=p["name"],
                advocate=p["advocate"],
                role=p["role"],
                raw_text=p["raw_text"]
            ))
            
        # Acts
        for a in data["acts"]:
            db.add(CaseAct(
                case_id=case_obj.id,
                act_name=a["act_name"],
                section=a["section"],
                act_code=a["act_code"]
            ))
            
        # History
        for h in data["history"]:
            db.add(CaseHistory(
                case_id=case_obj.id,
                business_date=h["business_date"],
                hearing_date=h["hearing_date"],
                purpose=h["purpose"],
                stage=h["stage"],
                notes=h["notes"],
                judge=h["judge"],
                source=h["source"]
            ))

        # Orders
        for o in data.get("orders", []):
            db.add(CaseOrder(
                case_id=case_obj.id,
                order_no=o.get("order_no"),
                order_date=o.get("order_date"),
                details=o.get("details"),
                pdf_filename=o.get("pdf_filename"),
                file_path=o.get("file_path"),
            ))
            
        db.commit()
        db.refresh(case_obj)
        return case_obj

    except Exception as e:
        db.rollback()
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/save-multiple/{session_id}")
async def save_multiple_cases(
    session_id: str,
    request: MultiSaveRequest,
    workspace_id: UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    Re-selects and saves multiple cases to DB.
    Backend authoritative scrape before saving.
    """
    saved_cases = []
    limits = get_user_plan_limits(current_user)

    pprint(request)

    if len(request.case_indices) > limits.multi_save:
        raise HTTPException(
            status_code=403,
            detail=f"Save limit exceeded ({limits.multi_save})"
        )

    try:
        for index in request.case_indices:

            # Select case
            await select_case(session_id, index)

            # Fetch structured data
            result = await fetch_results(session_id)

            if result.get("state") != "HISTORY_FETCHED" or not result.get("data"):
                continue  # skip silently or raise depending on your preference

            data = result["data"]["structured_data"]
            cino = data["cino"]

            # Check existing
            existing_case = db.query(Case).filter(
                Case.cino == cino,
                Case.workspace_id == workspace_id
            ).first()

            if existing_case:
                continue  # skip duplicates safely

            # ---- SAME LOGIC AS SINGLE SAVE ----

            case_obj = Case(
                workspace_id=workspace_id,
                cino=cino,
                title=data["title"],
                internal_status=data["internal_status"],
                court_name=data["court"]["name"],
                court_level=data["court"]["level"],
                court_bench=data["court"]["bench"],
                court_code=data["court"]["court_code"],
                summary_petitioner=data["summary"]["petitioner"],
                summary_respondent=data["summary"]["respondent"],
                summary_short_title=data["summary"]["short_title"],
                case_type=data["case_details"]["case_type"],
                filing_number=data["case_details"]["filing_number"],
                filing_date=data["case_details"]["filing_date"],
                registration_number=data["case_details"]["registration_number"],
                registration_date=data["case_details"]["registration_date"],
                first_hearing_date=data["status"]["first_hearing_date"],
                next_hearing_date=data["status"]["next_hearing_date"],
                last_hearing_date=data["status"]["last_hearing_date"],
                decision_date=data["status"]["decision_date"],
                case_stage=data["status"]["case_stage"],
                case_status_text=data["status"]["case_status_text"],
                nature_of_disposal=data["status"]["nature_of_disposal"],
                judge=data["status"]["judge"],
                meta_scraped_at=data["meta_scraped_at"],
                meta_source=data["meta_source"],
                meta_source_url=data["meta_source_url"],
                raw_html=data["raw_html"]
            )

            db.add(case_obj)
            db.flush()

            for p in data["parties"]:
                db.add(CaseParty(
                    case_id=case_obj.id,
                    is_petitioner=p["is_petitioner"],
                    name=p["name"],
                    advocate=p["advocate"],
                    role=p["role"],
                    raw_text=p["raw_text"]
                ))

            for a in data["acts"]:
                db.add(CaseAct(
                    case_id=case_obj.id,
                    act_name=a["act_name"],
                    section=a["section"],
                    act_code=a["act_code"]
                ))

            for h in data["history"]:
                db.add(CaseHistory(
                    case_id=case_obj.id,
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
                    case_id=case_obj.id,
                    order_no=o.get("order_no"),
                    order_date=o.get("order_date"),
                    details=o.get("details"),
                    pdf_filename=o.get("pdf_filename"),
                    file_path=o.get("file_path"),
                ))

            saved_cases.append(case_obj)

        db.commit()

        return {
            "saved_count": len(saved_cases),
            "cases": saved_cases
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/sidebar-init", response_model=SidebarInitResponse)
async def sidebar_init(
    request: SidebarInitRequest,
    current_user: User = Depends(deps.get_current_active_user)
):
    try:
        # 1️⃣ Start session using existing function
        session_id = await start_session(request.search_mode, request.payload)

        # 2️⃣ Get captcha using existing function
        img_bytes = await get_captcha(session_id)

        # 3️⃣ Encode for frontend
        captcha_base64 = base64.b64encode(img_bytes).decode()

        return SidebarInitResponse(
            session_id=session_id,
            captcha_base64=captcha_base64
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/sidebar-submit")
async def sidebar_submit(
    request: SidebarSubmitRequest,
    current_user: User = Depends(deps.get_current_active_user)
):
    try:
        session = await ScraperSession.get(request.session_id)

        # ✅ sync mode with sidebar form
        session.data["search_mode"] = request.search_mode

        # ✅ replace payload cleanly
        # session.data["payload"] = request.payload
        session.data["payload"] = build_ecourts_payload(
            session.search_mode,
            request.payload
        )
        session.is_dirty = True

        await session.save()

        pprint(session.data)

        await submit_captcha(request.session_id, request.captcha)

        return {
            "session_id": session.session_id,
            "state": session.state
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    