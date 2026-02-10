from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from app.schemas import StartCaseRequest, CaptchaSubmitRequest, SessionStatusResponse, CaseResultResponse, SelectCaseRequest
import app.schemas
from app.scraper.flows import start_session, get_captcha, submit_captcha, fetch_results
from app.scraper.session import ScraperSession
from app.scraper.errors import ECourtsError

router = APIRouter(prefix="/cases", tags=["cases"])

@router.post("/start", response_model=SessionStatusResponse)
async def start_case(request: StartCaseRequest):
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
            if not request.advocate_name:
                 raise HTTPException(status_code=400, detail="Advocate Name required")
            if not request.state_code or not request.dist_code or not request.court_complex_code:
                 raise HTTPException(status_code=400, detail="Location details (state, dist, complex) required")
            
            import time
            payload.update({
                'radAdvt': '1', 
                'advocate_name': request.advocate_name, 
                'case_status': request.case_status or 'Both',
                'adv_bar_state': '', 'adv_bar_code': '', 'adv_bar_year': '', 'case_type': '',
                'caselist_date': time.strftime("%d-%m-%Y"), # Current date generally required? logic from CLI
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
async def get_cases_list(session_id: str):
    """"Get list of cases for Party/Advocate search."""
    try:
        from app.scraper.flows import get_case_list
        return await get_case_list(session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/select/{session_id}")
async def select_case_route(session_id: str, request: StartCaseRequest): 
    # Re-using StartCaseRequest but only need index, or create new schema? 
    # Defined SelectCaseRequest in schemas
    pass 
    
    # Actually let's use the schema we defined
    return {} # Placeholder to be overridden by next replacement chunk
    
@router.post("/select-case/{session_id}")
async def select_case_endpoint(session_id: str, request: app.schemas.SelectCaseRequest):
    try:
        from app.scraper.flows import select_case
        result = await select_case(session_id, request.case_index)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/captcha/{session_id}")
async def get_captcha_image(session_id: str):
    try:
        img_bytes = await get_captcha(session_id)
        return Response(content=img_bytes, media_type="image/png")
    except ECourtsError as e:
         raise HTTPException(status_code=400, detail=str(e))

@router.post("/captcha/{session_id}")
async def submit_captcha_code(session_id: str, request: CaptchaSubmitRequest):
    try:
        await submit_captcha(session_id, request.captcha)
        return {"status": "submitted"}
    except ECourtsError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/status/{session_id}", response_model=SessionStatusResponse)
async def get_status(session_id: str):
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
async def get_case_pdf(session_id: str, filename: str):
    try:
        session = await ScraperSession.get(session_id)
        files = session.data.get("files", {})
        
        hex_content = files.get(filename)
        if not hex_content:
            raise HTTPException(status_code=404, detail="File not found")
            
        pdf_bytes = bytes.fromhex(hex_content)
        return Response(content=pdf_bytes, media_type="application/pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/result/{session_id}", response_model=CaseResultResponse)
async def get_result(session_id: str):
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