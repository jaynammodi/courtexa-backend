import requests
import time
import sys
import io
import pytesseract
from PIL import Image

BASE_URL = "http://localhost:8000"

def solve_captcha(img_bytes):
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img = img.convert('L')
        # Simple thresholding
        img = img.point(lambda p: 255 if p > 140 else 0)
        text = pytesseract.image_to_string(img, config='--psm 8')
        clean_text = "".join(c for c in text if c.isalnum())
        print(f"[*] OCR Result: {clean_text}")
        return clean_text
    except Exception as e:
        print(f"[-] OCR Failed: {e}")
        return input("Enter Captcha manually: ")

def verify_real_flow():
    print("[*] Starting REAL Verification Flow")
    
    # CNR to test
    # cnr = "UTDD010008222019" # The case with PDF
    cnr = "UTDD010001262024" # The case with missing dates/messy parties 
    print(f"[*] Post /cases/start with CNR: {cnr}")
    resp = requests.post(f"{BASE_URL}/cases/start", json={"search_mode": "cnr", "cnr": cnr})
    
    if resp.status_code != 200:
        print(f"[-] Failed to start session. Status: {resp.status_code}")
        print(f"[-] Response: {resp.text}")
        sys.exit(1)
        
    data = resp.json()
    session_id = data["session_id"]
    print(f"[+] Session Started: {session_id}, State: {data['state']}")

    # 2. Get Captcha
    print(f"[*] Get /cases/captcha/{session_id}")
    resp = requests.get(f"{BASE_URL}/cases/captcha/{session_id}")
    if resp.status_code != 200:
        print(f"[-] Failed to get captcha. Status: {resp.status_code}")
        sys.exit(1)
        
    captcha_code = solve_captcha(resp.content)
    if not captcha_code:
        captcha_code = "12345" # Fallback to force error if OCR fails empty

    # 3. Submit Captcha
    print(f"[*] Post /cases/captcha/{session_id} with code: {captcha_code}")
    resp = requests.post(f"{BASE_URL}/cases/captcha/{session_id}", json={"captcha": captcha_code})
    
    print(f"[+] Submit Response: {resp.json()}")

    # 4. Loop poll status
    for i in range(10):
        print(f"[*] Polling Status ({i+1})...")
        resp = requests.get(f"{BASE_URL}/cases/status/{session_id}")
        data = resp.json()
        print(f"[+] State: {data['state']}")
        
        if data['state'] == 'HISTORY_FETCHED' or data['state'] == 'SEARCH_SUBMITTED':
            print("[+] Success!")
            break
        
        if data['state'] == 'FAILED':
            print(f"[-] Failed: {data.get('last_error')}")
            break
            
        if data['state'] == 'CAPTCHA_REQUIRED':
             print("[-] Captcha Required (Invalid Captcha). Retrying flow not implemented here.")
             break
             
        time.sleep(1)

    print(f"[*] Get /cases/result/{session_id}")
    resp = requests.get(f"{BASE_URL}/cases/result/{session_id}")
    try:
        result = resp.json()
        print(f"[+] Full Response: {result}")
    except:
        print(f"[-] Failed to decode JSON. Text: {resp.text}")
        return

    if result.get("data") and result["data"].get("structured_data"):
        sd = result["data"]["structured_data"]
        
        print(f"[+] Refinement Check:")
        print(f"    - Title: {sd.get('title')}")
        print(f"    - Internal Status: {sd.get('internal_status')}")
        print(f"    - Court: {sd.get('court')}")
        print(f"    - Summary Petitioner: {sd.get('summary', {}).get('petitioner')}")
        print(f"    - Judge: {sd.get('status', {}).get('judge')}")
        print(f"    - Status: {sd.get('status', {}).get('case_status_text')}")
        print(f"    - Registration Date: {sd.get('case_details', {}).get('registration_date')}")
        print(f"    - Next Hearing: {sd.get('status', {}).get('next_hearing_date')}")
        print(f"    - First Hearing: {sd.get('status', {}).get('first_hearing_date')}")
        print(f"    - Case Stage: {sd.get('status', {}).get('case_stage')}")
        print(f"    - FIR: {sd.get('fir_details')}")
        print(f"    - Raw HTML Size: {len(sd.get('raw_html', ''))}")
        
        print(f"[+] Parties Sanity Check:")
        for p in sd.get("parties", []):
            print(f"    - {p['role']}: {p['name']} (Adv: {p['advocate']})")
            
        print(f"[+] Orders Check:")
        for o in sd.get("orders", []):
            print(f"    - Order {o['order_no']} | PDF: {o['pdf_filename']}")
            if o['pdf_filename']:
                print(f"      [*] Testing PDF Download: {o['pdf_filename']}...")
                pdf_resp = requests.get(f"{BASE_URL}/cases/pdf/{session_id}/{o['pdf_filename']}")
                if pdf_resp.status_code == 200:
                    print(f"      [+] PDF Download Success (Size: {len(pdf_resp.content)} bytes)")
                else:
                    print(f"      [-] PDF Download Failed: {pdf_resp.status_code}")

    else:
        print("[-] No structured data found.")

if __name__ == "__main__":
    verify_real_flow()
