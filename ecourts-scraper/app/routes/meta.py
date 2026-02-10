from fastapi import APIRouter, HTTPException, Query
from app.scraper.client import ECourtsClient
from app.scraper.utils import parse_options_html
from bs4 import BeautifulSoup

router = APIRouter()

@router.get("/states")
async def get_states():
    client = ECourtsClient()
    try:
        token, home_html = client.get_initial_token()
        print(f"DEBUG: Meta get_states - HTML len: {len(home_html) if home_html else 0}")
        
        if not home_html:
             raise HTTPException(status_code=500, detail="Failed to load eCourts homepage")
        
        soup = BeautifulSoup(home_html, 'html.parser')
        state_select = soup.find('select', id='sess_state_code')
        
        if not state_select:
             print("DEBUG: State select element not found in HTML")
             # Dump HTML to file for inspection if needed
             with open("debug_meta_home.html", "w") as f: f.write(home_html)
             raise HTTPException(status_code=500, detail="State dropdown not found")
             
        states = parse_options_html(str(state_select))
        print(f"DEBUG: Found {len(states)} states")
        return {"states": states}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/districts/{state_code}")
async def get_districts(state_code: str):
    client = ECourtsClient()
    # We need a session/token to make this request? 
    # Usually getting initial token is enough for the session
    client.get_initial_token() 
    
    try:
        resp = client.get_districts(state_code)
        districts = parse_options_html(resp.text)
        return {"districts": districts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/complexes/{state_code}/{dist_code}")
async def get_complexes(state_code: str, dist_code: str):
    client = ECourtsClient()
    client.get_initial_token()
    
    try:
        resp = client.get_complexes(state_code, dist_code)
        complexes = parse_options_html(resp.text)
        return {"complexes": complexes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
