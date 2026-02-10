import requests
import time
import sys
from verify import solve_captcha

BASE_URL = "http://localhost:8000"

def test_party_search():
    print("\n[=] Testing Party Search...")
    
    # 1. Fetch Metadata (Daman)
    # State: Daman & Diu (Code 25? need to check, usually Daman is 25 or UT logic)
    # Let's rely on what we know or fetch it
    print("[*] Fetching States...")
    resp = requests.get(f"{BASE_URL}/meta/states")
    states = resp.json().get("states", [])
    daman_state = next((s for s in states if "Daman" in s['text']), None)
    
    if not daman_state:
        print(f"[-] Daman state not found in metadata. Available: {[s['text'] for s in states]}")
        return

    print(f"[+] Found State: {daman_state['text']} ({daman_state['value']})")
    
    # District
    print(f"[*] Fetching Districts for {daman_state['text']}...")
    resp = requests.get(f"{BASE_URL}/meta/districts/{daman_state['value']}")
    districts = resp.json().get("districts", [])
    daman_dist = next((d for d in districts if "Daman" in d['text']), None)
    
    if not daman_dist:
        print("[-] Daman district not found.")
        return
    print(f"[+] Found District: {daman_dist['text']} ({daman_dist['value']})")

    # Complex
    print(f"[*] Fetching Complexes...")
    resp = requests.get(f"{BASE_URL}/meta/complexes/{daman_state['value']}/{daman_dist['value']}")
    complexes = resp.json().get("complexes", [])
    if not complexes:
        print("[-] No complexes found.")
        return
    
    target_complex = complexes[0] # Just pick first
    print(f"[+] Selected Complex: {target_complex['text']} ({target_complex['value']})")

    # 2. Start Session
    print("[*] Starting Party Search Session...")
    payload = {
        "search_mode": "party",
        "party_name": "State", 
        "registration_year": "2024",
        "case_status": "Both",
        "state_code": daman_state['value'],
        "dist_code": daman_dist['value'],
        "court_complex_code": target_complex['value']
    }
    
    resp = requests.post(f"{BASE_URL}/cases/start", json=payload)
    if resp.status_code != 200:
        print(f"[-] Failed start: {resp.text}")
        return
        
    session_id = resp.json()["session_id"]
    print(f"[+] Session: {session_id}")

    # 3. Captcha
    resp = requests.get(f"{BASE_URL}/cases/captcha/{session_id}")
    captcha_code = solve_captcha(resp.content)
    if not captcha_code: captcha_code = "12345"
    
    print(f"[*] Submitting Captcha: {captcha_code}")
    requests.post(f"{BASE_URL}/cases/captcha/{session_id}", json={"captcha": captcha_code})

    # 4. Poll for List
    case_list = []
    print("[*] Polling for Case List...")
    for i in range(10):
        resp = requests.get(f"{BASE_URL}/cases/status/{session_id}")
        state = resp.json()['state']
        print(f"    State: {state}")
        
        if state == "CASE_LIST_LOADED":
            # Get List
            resp_list = requests.get(f"{BASE_URL}/cases/list/{session_id}")
            case_list = resp_list.json().get("cases", [])
            print(f"[+] Case List Loaded! Found {len(case_list)} cases.")
            break
        
        if state == "FAILED":
            print(f"[-] Failed: {resp.json().get('last_error')}")
            return
            
        time.sleep(1)
        
    if not case_list:
        print("[-] No cases found or list load failed.")
        return

    # Print first 5
    for c in case_list[:5]:
        print(f"    [{c['index']}] {c['display']}")
        
    # 5. Select First Case
    target_case_idx = case_list[0]['index']
    print(f"[*] Selecting Case Index {target_case_idx}...")
    
    resp = requests.post(f"{BASE_URL}/cases/select-case/{session_id}", json={"case_index": target_case_idx})
    if resp.status_code != 200:
        print(f"[-] Selection Failed: {resp.text}")
        return
        
    print("[+] Selection Submitted. Polling for Details...")
    
    # 6. Poll for Details
    for i in range(10):
        resp = requests.get(f"{BASE_URL}/cases/status/{session_id}")
        state = resp.json()['state']
        print(f"    State: {state}")
        
        if state == "SEARCH_SUBMITTED" or state == "HISTORY_FETCHED":
            # Get Result
            res = requests.get(f"{BASE_URL}/cases/result/{session_id}").json()
            if res.get('data'):
                sd = res['data']['structured_data']
                print(f"[+] Success! Case: {sd['title']}")
                print(f"    Status: {sd['internal_status']}")
                print(f"    Filings: {len(sd['history_rows'] or [])} history rows")
                return
            else:
                 print("[-] Result fetched but no data?")
                 return

        if state == "FAILED":
             print(f"[-] Failed: {resp.json().get('last_error')}")
             return

        time.sleep(1)

if __name__ == "__main__":
    test_party_search()
