import asyncio
from typing import Dict, Any, Optional
from fastapi.concurrency import run_in_threadpool

from app.services.scraper.session import ScraperSession, STATE_INIT, STATE_CAPTCHA_REQUIRED, STATE_CAPTCHA_SUBMITTED, STATE_SEARCH_SUBMITTED, STATE_HISTORY_FETCHED, STATE_FAILED, STATE_COMPLETED, STATE_CASE_LIST_LOADED
import re
from bs4 import BeautifulSoup
from app.services.scraper.client import ECourtsClient
from app.services.scraper.processor import sanitize_html, extract_css_links, parse_full_case_data, clean_text
from app.services.scraper.transformer import transform_to_schema
from app.services.scraper.errors import TokenError, CaptchaError, RetryableError
from app.services.scraper.ocr import solve_captcha

async def start_session(search_mode: str, payload: Dict[str, Any]) -> str:
    session = await ScraperSession.create(search_mode, payload)
    
    # Run initial token fetch in threadpool
    try:
        client = ECourtsClient()
        token, _ = await run_in_threadpool(client.get_initial_token)
    except Exception as e:
        session.set_error(f"Failed to obtain initial token: {e}")
        await session.save()
        raise e
    
    if not token:
        session.set_error("Failed to obtain initial token")
        await session.save()
        raise TokenError("Failed to obtain initial token from eCourts")

    # Update session with token and cookies
    session.app_token = token
    session.cookies = client.get_cookies()
    session.state = STATE_CAPTCHA_REQUIRED
    await session.save()
    
    return session.session_id

async def get_captcha(session_id: str) -> bytes:
    session = await ScraperSession.get(session_id)
    
    client = ECourtsClient(cookies=session.cookies, current_token=session.app_token)
    img_bytes = await run_in_threadpool(client.get_captcha)
    
    # Update session cookies/token in case they changed
    session.cookies = client.get_cookies()
    if client.current_token:
        session.app_token = client.current_token
        
    await session.save()
    return img_bytes

async def submit_captcha(session_id: str, captcha_code: str):
    session = await ScraperSession.get(session_id)
    
    # Validate state
    if session.state not in [STATE_CAPTCHA_REQUIRED, STATE_FAILED, STATE_CASE_LIST_LOADED]:
        pass

    session.update_payload({"fcaptcha_code": captcha_code})
    
    client = ECourtsClient(cookies=session.cookies, current_token=session.app_token)
    
    # Prepare payload based on mode
    mode = session.search_mode
    payload = session.data.get("payload", {}).copy()
    
    # --- LOCATIONAL DATA LOCKING (For Party/Advocate) ---
    if mode in ['party', 'advocate']:
        # Ensure location is set on the server session
        # Payload should have state_code, dist_code, court_complex_code
        state = payload.get('state_code')
        dist = payload.get('dist_code')
        complex_code = payload.get('court_complex_code')
        
        if state and dist and complex_code:
            # We run this sync in threadpool to ensure session on server is updated
            resp = await run_in_threadpool(client.set_data, state, dist, complex_code)
            print(f"DEBUG: set_data response: {resp.text[:200]}")
    
    # Perform search with retry logic
    attempts = 0
    max_attempts = 2
    
    while attempts < max_attempts:
        attempts += 1
        try:
             # Ensure client has fresh token from session if it changed
            if session.app_token:
                client.current_token = session.app_token

            print(f"DEBUG: submit_captcha Attempt {attempts} | Mode: {mode} | Token: {client.current_token[:10]}...")
            
            response = None
            if mode == 'cnr':
                search_payload = {
                     "cino": payload.get("cnr"),
                     "fcaptcha_code": captcha_code
                }
                response = await run_in_threadpool(client.search_cnr, search_payload)
            
            elif mode == 'party':
                # payload already has structure from start_session, but we need to clean complex code
                search_payload = payload.copy() # Don't mutate session payload
                search_payload['fcaptcha_code'] = captcha_code
                
                # Check complex code and clean if necessary
                cc = search_payload.get('court_complex_code', '')
                if '@' in cc:
                    search_payload['court_complex_code'] = cc.split('@')[0]
                    
                response = await run_in_threadpool(client.search_party, search_payload)
                
            elif mode == 'advocate':
                search_payload = payload.copy()
                search_payload['adv_captcha_code'] = captcha_code
                
                cc = search_payload.get('court_complex_code', '')
                if '@' in cc:
                    search_payload['court_complex_code'] = cc.split('@')[0]
                
                response = await run_in_threadpool(client.search_advocate, search_payload)
            
            if not response:
                raise Exception("Search method not implemented or failed")

            try:
                result_json = response.json()
            except:
                 print(f"DEBUG: Invalid JSON. Response text: {response.text[:500]}...")
                 raise RetryableError("Invalid JSON response from eCourts")

            # Check for token refresh in response
            new_token = result_json.get('app_token')
            if new_token and new_token != session.app_token:
                print(f"DEBUG: Token refreshed in search response: {new_token[:10]}...")
                session.app_token = new_token
                await session.save()
                
                # If we got an error message with a new token, we MUST retry
                if result_json.get('errormsg'):
                     print(f"DEBUG: Error with new token, retrying... Msg: {result_json.get('errormsg')}")
                     continue

            if "Invalid Captcha" in str(result_json):
                session.state = STATE_CAPTCHA_REQUIRED
                await session.save()
                raise CaptchaError("Invalid Captcha")
            
            if "No Record Found" in str(result_json):
                 session.state = STATE_FAILED
                 session.set_error("No Record Found")
                 await session.save()
                 return

            # --- SUCCESS PATHS ---
            
            # Path A: Direct Details (CNR)
            html_content = result_json.get('cino_data') or result_json.get('data_list') or result_json.get('casetype_list')
            
            # Additional check for CNR: sometimes 'cino' search returns raw HTML in weird keys? 
            # Usually cino_data
            
            if mode == 'cnr' and html_content:
                session.update_payload({"result_html": html_content})
                session.state = STATE_SEARCH_SUBMITTED
                await session.save()
                return 

            # Path B: Case List (Party/Advocate)
            # data keys: party_data or adv_data
            list_html = result_json.get('party_data') or result_json.get('adv_data') or result_json.get('data_list')
            
            if mode in ['party', 'advocate'] and list_html:
                session.update_payload({"list_html": list_html})
                session.state = STATE_CASE_LIST_LOADED
                await session.save()
                return

            # If we are here, we might have an error message or just no data
            err_msg = result_json.get('errormsg', 'Unknown Error')
            print(f"DEBUG: Search failed but no exception. Msg: {err_msg}")
            
            if "Invalid Request" in err_msg or "Something went wrong" in err_msg:
                # Likely token issue or transient failure. Retry if attempts left.
                if attempts < max_attempts:
                    continue

            session.state = STATE_FAILED
            session.set_error(f"Search failed: {err_msg}")
            await session.save()
            return
            
        except Exception as e:
            print(f"DEBUG: Exception in search attempt {attempts}: {e}")
            if attempts >= max_attempts:
                session.set_error(str(e))
                await session.save()
                raise e

async def fetch_results(session_id: str) -> Dict[str, Any]:
    print(f"DEBUG: fetch_results for {session_id}")
    session = await ScraperSession.get(session_id)
    
    if session.state == STATE_SEARCH_SUBMITTED or session.state == STATE_HISTORY_FETCHED:
        # Process the stored HTML
        raw_html_content = session.data["payload"].get("result_html")
        
        # 1. Parse Basic Structure
        # We use the existing sanitization for the visual view
        clean_html = sanitize_html(raw_html_content)
        css_links = extract_css_links(raw_html_content)
        
        # 2. Parse Deep Data
        parsed_data = parse_full_case_data(raw_html_content)
        
        # 3. Fetch Business Status for each history row
        client = ECourtsClient(cookies=session.cookies, current_token=session.app_token)
        
        if parsed_data.get("history_rows"):
            print(f"DEBUG: Fetching business details for {len(parsed_data['history_rows'])} rows...")
            for row in parsed_data["history_rows"]:
                b_args = row.get("business_link_args")
                if b_args and len(b_args) >= 9:
                    try:
                        # Construct payload as per reference
                        b_payload = {
                            'court_code': b_args[0], 
                            'state_code': b_args[4] if len(b_args) > 4 else '', 
                            'dist_code': 'undefined',
                            'case_number1': b_args[3] if len(b_args) > 3 else '', 
                            'disposal_flag': b_args[5] if len(b_args) > 5 else '', 
                            'businessDate': b_args[6] if len(b_args) > 6 else '',
                            'national_court_code': b_args[8] if len(b_args) > 8 else '', 
                            'court_no': b_args[7] if len(b_args) > 7 else '', 
                            'search_by': 'cnr', 
                            'srno': b_args[10] if len(b_args) > 10 else '0', 
                            'nextdate1': b_args[2] if len(b_args) > 2 else ''
                        }
                        # Run sync request in threadpool
                        biz_text = await run_in_threadpool(client.view_business, b_payload)
                        row["business_update"] = biz_text
                    except Exception as e:
                        print(f"WARN: Failed to fetch business for row: {e}")
                        row["business_update"] = "Failed to fetch"
                else:
                    row["business_update"] = "N/A"
        
        # 4. Process PDF Links (Download Orders)
        if parsed_data.get("orders"):
            files = session.data.get("files", {})
            print(f"DEBUG: Processing {len(parsed_data['orders'])} orders for PDF...")
            
            for idx, row in enumerate(parsed_data["orders"]):
                p_args = row.get("pdf_link_args")
                if p_args and len(p_args) >= 4:
                    try:
                         # Construct payload
                         # displayPdf('normal_v', 'case_val', 'court_code', 'filename', 'appFlag')
                         p_payload = {
                            'normal_v': p_args[0], 'case_val': p_args[1], 
                            'court_code': p_args[2], 'filename': p_args[3],
                            'appFlag': p_args[4] if len(p_args) > 4 else ''
                         }
                         
                         filename_local = f"order_{idx+1}.pdf"
                         
                         # 1. Trigger Generation
                         await run_in_threadpool(client.display_pdf, p_payload)
                         
                         # 2. Download Bytes
                         # Note: display_pdf usually returns HTML/Text status, the PDF is at report URL
                         # We need to wait a sec? Sync script slept 1s.
                         await asyncio.sleep(1) 
                         
                         pdf_bytes = await run_in_threadpool(client.get_pdf_bytes)
                         
                         if pdf_bytes:
                             files[filename_local] = pdf_bytes.hex() # Store as hex string (JSON serializable)
                             row["pdf_filename"] = filename_local
                             print(f"DEBUG: Downloaded {filename_local}")
                         else:
                             print(f"WARN: Failed to download PDF bytes for order {idx+1}")
                             
                    except Exception as e:
                        print(f"WARN: Failed to process PDF for order {idx+1}: {e}")
            
            # Update session with files
            session.data["files"] = files
            await session.save()

        # 5. Transform to Pydantic Schema
        # Add metadata to parsed_data for transformer
        # parsed_data["raw_html"] is already added by parse_full_case_data if checking there, but actually no
        parsed_data["raw_html"] = clean_html # Use the sanitized HTML
        parsed_data["meta_url"] = "https://services.ecourts.gov.in/ecourtindia_v6/"
        
        cino = session.data["payload"].get("cnr", "Unknown")
        structured_model = transform_to_schema(parsed_data, cino)
        structured_schema_dict = structured_model.model_dump(mode='json')

        result = {
            "state": session.state,
            "data": {
                "structured_data": structured_schema_dict,
                "history_html": clean_html,
                "css_links": css_links,
            }
        }

        # Update session state
        if session.state != STATE_HISTORY_FETCHED:
            session.state = STATE_HISTORY_FETCHED
            await session.save()
        
        result["state"] = session.state
        return result
    
    else:
        return {"state": session.state, "error": session.data.get("last_error")}

async def get_case_list(session_id: str):
    """"For Party/Advocate search, returns the list of cases to select from."""
    session = await ScraperSession.get(session_id)
    
    # Allow extraction if we are in LIST_LOADED or if we already submitted a search (re-selection)
    if session.state not in [STATE_CASE_LIST_LOADED, STATE_SEARCH_SUBMITTED, STATE_HISTORY_FETCHED]:
        return {"state": session.state, "cases": []}
    
    list_html = session.data["payload"].get("list_html")
    if not list_html:
        return {"state": session.state, "cases": []}
        
    soup = BeautifulSoup(list_html, 'html.parser')
    cases = []
    
    # Parse table rows 
    # eCourts returns a table with rows having onclick
    for idx, row in enumerate(soup.find_all('tr')):
        cols = row.find_all('td')
        if len(cols) < 3: continue
        
        # Extract text for display
        cnr_txt = clean_text(cols[0].text) # Usually first col is CNR or SR No
        pet_txt = clean_text(cols[1].text)
        res_txt = clean_text(cols[2].text)
        
        full_text = f"{cnr_txt} | {pet_txt} vs {res_txt}"
        
        link = row.find('a', onclick=re.compile(r'viewHistory'))
        if link:
            cases.append({
                "index": idx,
                "display": full_text,
                "cnr": cnr_txt, # Might not be actual CNR, but display text
                "petitioner": pet_txt,
                "respondent": res_txt,
                "onclick": link['onclick']
            })
            
    return {"state": session.state, "cases": cases}

async def select_case(session_id: str, case_index: int):
    """Triggers viewHistory for the selected case."""
    session = await ScraperSession.get(session_id)
    
    # 1. Get List logic re-run to find the onclick args (inefficient but stateless)
    data = await get_case_list(session_id)
    cases = data['cases']
    
    selected_case = next((c for c in cases if c['index'] == case_index), None)
    if not selected_case:
        raise Exception("Invalid Case Index")
        
    onclick = selected_case['onclick']
    # Extract args: viewHistory(case_no, cino, court_code, hideparty, search_flag, state_code, dist_code, court_complex_code, search_by)
    match = re.search(r"viewHistory\((.*?)\)", onclick)
    if not match:
        raise Exception("Failed to parse viewHistory args")
        
    args = [arg.strip().strip("'").strip('"') for arg in match.group(1).split(',')]
    
    # 2. Call viewHistory
    client = ECourtsClient(cookies=session.cookies, current_token=session.app_token)
    
    payload = {
        'case_no': args[0], 'cino': args[1], 'court_code': args[2], 'hideparty': args[3],
        'search_flag': args[4], 'state_code': args[5], 'dist_code': args[6],
        'court_complex_code': args[7], 'search_by': args[8]
    }
    
    print(f"DEBUG: select_case fetching case details for CNR {args[1]}...")
    resp = await run_in_threadpool(client.view_history, payload)
    
    try:
        data = resp.json()
    except:
        raise Exception("Invalid JSON from viewHistory")
    
    html_content = data.get('data_list') or data.get('cino_data')
    
    if html_content:
        # Update session to SEARCH_SUBMITTED with this HTML
        session.update_payload({"result_html": html_content, "cnr": args[1]}) # Update CNR to selected one
        session.state = STATE_SEARCH_SUBMITTED
        await session.save()
        
        # Parse metadata for verification (Metadata Only)
        from app.services.scraper.processor import parse_case_metadata
        parsed = parse_case_metadata(html_content)
        details = parsed.get("case_details", {})
        status = parsed.get("status", {})
        
        # Parse Status & Disposal
        status_text = status.get("Case Status", "")
        nature_of_disposal = ""
        current_status = "Active" 
        
        if "disposed" in status_text.lower():
            current_status = "Disposed"
            if "-" in status_text:
                # e.g. "Case disposed - Contested--ORDER"
                parts = status_text.split("-", 1)
                if len(parts) > 1:
                    nature_of_disposal = parts[1].strip()

        metadata = {
            "case_type": details.get("Case Type"),
            "filing_number": details.get("Filing Number"),
            "filing_date": details.get("Filing Date"),
            "registration_number": details.get("Registration Number"),
            "registration_date": details.get("Registration Date"),
            "cnr": details.get("CNR Number") or args[1],
            
            "first_hearing_date": status.get("First Hearing Date"),
            "next_hearing_date": status.get("Next Hearing Date"),
            "last_hearing_date": status.get("Last Hearing Date"),
            "decision_date": status.get("Decision Date"),
            "case_stage": status.get("Case Stage"),
            "court_number_and_judge": status.get("Court Number and Judge"),
            "case_status_text": status_text,
            "nature_of_disposal": nature_of_disposal,
            "current_status": current_status,
            
            "petitioner": parsed.get("petitioner"),
            "respondent": parsed.get("respondent"),
            "court_heading": parsed.get("court_heading")
        }
        
        return {"status": "success", "cnr": args[1], "metadata": metadata}
    else:
        raise Exception("No HTML content in viewHistory response")

async def refresh_case(cnr: str, max_retries: int = 5) -> Dict[str, Any]:
    """
    Automated flow to refresh a case by CNR.
    Retries entire flow including OCR failures.
    """
    print(f"DEBUG: Starting automated refresh for {cnr}")
    
    for attempt in range(max_retries):
        try:
            # 1. Start Session
            session_id = await start_session("cnr", {"cnr": cnr})
            
            # 2. Get Captcha
            img_bytes = await get_captcha(session_id)
            
            # 3. Solve Captcha (OCR)
            captcha_code = await run_in_threadpool(solve_captcha, img_bytes)
            
            if not captcha_code or len(captcha_code) < 3:
                print(f"DEBUG: OCR failed or weak (attempt {attempt+1})")
                continue # Retry fresh session
                
            print(f"DEBUG: OCR Solved: {captcha_code}")
            
            # 4. Submit Captcha
            try:
                await submit_captcha(session_id, captcha_code)
            except CaptchaError:
                print(f"DEBUG: Invalid Captcha (attempt {attempt+1})")
                continue
                
            # 5. Check Result
            session = await ScraperSession.get(session_id)
            if session.state == STATE_SEARCH_SUBMITTED:
                # Success! Fetch full results
                result = await fetch_results(session_id)
                return result
            else:
                 print(f"DEBUG: Flow failed state={session.state} (attempt {attempt+1})")
        
        except Exception as e:
            print(f"DEBUG: Refresh Exception (attempt {attempt+1}): {e}")
            
    raise Exception(f"Failed to refresh case {cnr} after {max_retries} attempts")
