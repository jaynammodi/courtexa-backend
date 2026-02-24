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
from app.services.storage import get_storage
import requests
from http.client import RemoteDisconnected

from rich import print

RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    RemoteDisconnected,
    RetryableError,
)

async def retry_request(func, *args, attempts=3, delay=1, **kwargs):
    last_exception = None

    for attempt in range(attempts):
        try:
            return await run_in_threadpool(func, *args, **kwargs)
        except RETRYABLE_EXCEPTIONS as e:
            print(f"[bold red]REQUEST RETRY[/bold red]: Attempt {attempt+1} failed: {e}")
            last_exception = e
            await asyncio.sleep(delay)

    raise last_exception

VS_PATTERN = re.compile(r'(?i)(?:\s*)(?:v\/?s\.?|vs\.?|v\.)(?:\s*)')

def split_parties(raw_parties: str):
    parts = VS_PATTERN.split(raw_parties, maxsplit=1)

    if len(parts) != 2:
        return {
            "petitioner": raw_parties.strip(),
            "respondent": None,
            "error": "Could not split parties"
        }

    petitioner = parts[0].strip()
    respondent = parts[1].strip()

    return {
        "petitioner": petitioner,
        "respondent": respondent
    }


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

    session.update_payload({"fcaptcha_code": captcha_code})

    client = ECourtsClient(
        cookies=session.cookies,
        current_token=session.app_token
    )

    mode = session.search_mode
    payload = session.data.get("payload", {}).copy()

    max_attempts = 5   # 🔥 NOW 5 ATTEMPTS
    attempts = 0

    while attempts < max_attempts:
        attempts += 1
        try:
            if session.app_token:
                client.current_token = session.app_token

            print(f"[bold bright_magenta]ECOURTS[/bold bright_magenta]: submit_captcha Attempt {attempts} | Mode: {mode}")

            if mode == 'cnr':
                search_payload = {
                    "cino": payload.get("cnr"),
                    "fcaptcha_code": captcha_code
                }
                response = await retry_request(
                    client.search_cnr,
                    search_payload,
                    attempts=3
                )

            elif mode == 'party':
                search_payload = payload.copy()
                search_payload['fcaptcha_code'] = captcha_code

                cc = search_payload.get('court_complex_code', '')
                if '@' in cc:
                    search_payload['court_complex_code'] = cc.split('@')[0]

                response = await retry_request(
                    client.search_party,
                    search_payload,
                    attempts=3
                )

            elif mode == 'advocate':
                search_payload = payload.copy()
                search_payload['adv_captcha_code'] = captcha_code

                cc = search_payload.get('court_complex_code', '')
                if '@' in cc:
                    search_payload['court_complex_code'] = cc.split('@')[0]

                response = await retry_request(
                    client.search_advocate,
                    search_payload,
                    attempts=3
                )

            else:
                raise Exception("Invalid search mode")

            result_json = response.json()

            # Token refresh
            new_token = result_json.get('app_token')
            if new_token and new_token != session.app_token:
                session.app_token = new_token
                await session.save()

            if "Invalid Captcha" in str(result_json):
                raise CaptchaError("Invalid Captcha")

            if "No Record Found" in str(result_json):
                session.state = STATE_FAILED
                session.set_error("No Record Found")
                await session.save()
                return

            html_content = (
                result_json.get('cino_data')
                or result_json.get('data_list')
                or result_json.get('casetype_list')
            )

            if mode == 'cnr' and html_content:
                session.update_payload({"result_html": html_content})
                session.state = STATE_SEARCH_SUBMITTED
                await session.save()
                return

            list_html = (
                result_json.get('party_data')
                or result_json.get('adv_data')
            )

            if mode in ['party', 'advocate'] and list_html:
                session.update_payload({"list_html": list_html})
                session.state = STATE_CASE_LIST_LOADED
                await session.save()
                return

        except CaptchaError:
            print(f"[bold red]ECOURTS[/bold red]: [bold red]ERROR[/bold red]: Invalid captcha on attempt {attempts}")
            if attempts >= max_attempts:
                raise
            continue

        except Exception as e:
            print(f"[bold red]ECOURTS[/bold red]: [bold red]ERROR[/bold red]: Search attempt {attempts} failed: {e}")
            if attempts >= max_attempts:
                session.set_error(str(e))
                await session.save()
                raise
            await asyncio.sleep(1)

async def fetch_results(session_id: str) -> Dict[str, Any]:
    print(f"[bold magenta]DEBUG[/bold magenta]: fetch_results for {session_id}")
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
            print(f"[bold bright_magenta]ECOURTS[/bold bright_magenta]: [bold bright_magenta]DEBUG[/bold bright_magenta]: Fetching history business details for {len(parsed_data['history_rows'])} rows...")
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
                        # biz_text = await run_in_threadpool(client.view_business, b_payload)
                        biz_text = await retry_request(
                            client.view_business,
                            b_payload,
                            attempts=3
                        )

                        # 🔥 CRITICAL FIX
                        session.app_token = client.current_token
                        session.cookies = client.get_cookies()
                        await session.save()

                        row["business_update"] = biz_text
                    except Exception as e:
                        print(f"[bold yellow]WARN[/bold yellow]: Failed to fetch business for row: {e}")
                        row["business_update"] = "Failed to fetch"
                else:
                    row["business_update"] = "N/A"
        
        # 4. Process PDF Links (Download Orders)
        if parsed_data.get("orders"):
            files = session.data.get("files", {})
            print(f"[bold blue]PDF[/bold blue]: [bold blue]DEBUG[/bold blue]: Processing {len(parsed_data['orders'])} orders for PDF...")
            
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

                        # 1️⃣ Trigger PDF generation with retry
                        await retry_request(
                            client.display_pdf,
                            p_payload,
                            attempts=3
                        )

                        # Persist updated token
                        session.app_token = client.current_token
                        session.cookies = client.get_cookies()
                        await session.save()

                        await asyncio.sleep(1)

                        # 2️⃣ Download PDF with retry
                        pdf_bytes = await retry_request(
                            client.get_pdf_bytes,
                            attempts=3
                        )

                        if pdf_bytes:
                            storage = get_storage()
                            storage_path = f"{session_id}/{filename_local}"
                            saved_path = await storage.save(storage_path, pdf_bytes)

                            files[filename_local] = saved_path
                            row["pdf_filename"] = filename_local
                            row["file_path"] = saved_path
                            row["file_size"] = len(pdf_bytes)

                            print(f"[bold blue]PDF[/bold blue]: [bold green]SUCCESS[/bold green]: Downloaded {filename_local}")
                        else:
                            print(f"[bold blue]PDF[/bold blue]: [bold yellow]WARN[/bold yellow]: Failed to download PDF bytes for order {idx+1}")
                             
                    except Exception as e:
                        print(f"[bold blue]PDF[/bold blue]: [bold yellow]WARN[/bold yellow]: Failed to process PDF for order {idx+1}: {e}")
            
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
        sr_no = clean_text(cols[0].text) # Usually first col is CNR or SR No
        case_number = clean_text(cols[1].text)
        raw_parties = clean_text(cols[2].text)

        parties = split_parties(raw_parties)
        pet_txt = parties["petitioner"]
        res_txt = parties["respondent"]
        
        full_text = f"{sr_no} | {case_number} | {pet_txt} vs {res_txt}"
        
        link = row.find('a', onclick=re.compile(r'viewHistory'))
        if link:
            cases.append({
                "index": idx,
                "display": full_text,
                "case_number": case_number,
                "petitioner": pet_txt,
                "respondent": res_txt,
                "onclick": link['onclick']
            })
    print(f"[bold blue]CASE LIST[/bold blue]: [bold blue]DEBUG[/bold blue]: Found {len(cases)} cases")
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
    
    print(f"[bold blue]CASE LIST[/bold blue]: [bold blue]DEBUG[/bold blue]: select_case fetching case details for CNR {args[1]}...")
    resp = await run_in_threadpool(client.view_history, payload)

    # 🔥 Persist updated token + cookies
    session.app_token = client.current_token
    session.cookies = client.get_cookies()
    await session.save()
    
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
            "court_heading": parsed.get("court_heading"),
            "case_index": case_index
        }
        
        return {"status": "success", "cnr": args[1], "metadata": metadata}
    else:
        raise Exception("No HTML content in viewHistory response")

async def refresh_case(cnr: str, max_retries: int = 5) -> Dict[str, Any]:
    """
    Automated flow to refresh a case by CNR.
    Retries entire flow including OCR failures.
    """
    print(f"[bold blue]REFRESH[/bold blue]: [bold blue]DEBUG[/bold blue]: Starting automated refresh for {cnr}")
    
    for attempt in range(max_retries):
        try:
            # 1. Start Session
            session_id = await start_session("cnr", {"cnr": cnr})
            
            # 2. Get Captcha
            img_bytes = await get_captcha(session_id)
            
            # 3. Solve Captcha (OCR)
            captcha_code = await run_in_threadpool(solve_captcha, img_bytes)
            
            if not captcha_code or len(captcha_code) < 3:
                print(f"[bold blue]REFRESH[/bold blue]: [bold yellow]WARN[/bold yellow]: OCR failed or weak (attempt {attempt+1})")
                continue # Retry fresh session
                
            print(f"[bold blue]REFRESH[/bold blue]: [bold blue]DEBUG[/bold blue]: OCR Solved: {captcha_code}")
            
            # 4. Submit Captcha
            try:
                await submit_captcha(session_id, captcha_code)
            except CaptchaError:
                print(f"[bold blue]REFRESH[/bold blue]: [bold yellow]WARN[/bold yellow]: Invalid Captcha (attempt {attempt+1})")
                continue
                
            # 5. Check Result
            session = await ScraperSession.get(session_id)
            if session.state == STATE_SEARCH_SUBMITTED:
                # Success! Fetch full results
                result = await fetch_results(session_id)
                return result
            else:
                print(f"[bold blue]REFRESH[/bold blue]: [bold yellow]WARN[/bold yellow]: Flow failed state={session.state} (attempt {attempt+1})")
        
        except Exception as e:
            print(f"[bold blue]REFRESH[/bold blue]: [bold red]ERROR[/bold red]: Refresh Exception (attempt {attempt+1}): {e}")
            
    raise Exception(f"[bold blue]REFRESH[/bold blue]: [bold red]ERROR[/bold red]: Failed to refresh case {cnr} after {max_retries} attempts")

