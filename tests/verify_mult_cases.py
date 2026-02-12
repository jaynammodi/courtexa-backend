import urllib.request
import urllib.parse
import json
import random
import sys
from pprint import pprint

API_URL = "http://127.0.0.1:8000/api/v1"
WORKSPACE_ID = "20cf75e5-c39c-4adf-a589-cb82b57a677f"

def divider(title):
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)

def ok(msg):
    print(f"✅ {msg}")

def fail(msg):
    print(f"❌ {msg}")
    sys.exit(1)

def api_request(path, method="GET", data=None, token=None):
    url = f"{API_URL}{path}"

    if data:
        data = json.dumps(data).encode()

    req = urllib.request.Request(url, data=data, method=method)

    if token:
        req.add_header("Authorization", f"Bearer {token}")

    if data:
        req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req) as resp:
        if resp.status == 204:
            return None
        return json.load(resp)


def login():
    divider("AUTHENTICATION")

    login_data = urllib.parse.urlencode({
        "username": "lawyer@demo.com",
        "password": "password123"
    }).encode()

    req = urllib.request.Request(
        f"{API_URL}/auth/login",
        data=login_data,
        method="POST"
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
        token = data["access_token"]
        ok("Login successful")
        return token


def start_party_search(token):
    divider("START PARTY SEARCH (raj, 2026)")

    payload = {
        "search_mode": "party",
        "party_name": "raj",
        "registration_year": "2026",
        "case_status": "Both",
        # YOU MUST PROVIDE VALID LOCATION VALUES
        "state_code": "38",  # example – adjust if needed
        "dist_code": "2",
        "court_complex_code": "1310006@1@N"
    }

    result = api_request("/scraper/start", "POST", payload, token)
    pprint(result)

    session_id = result["session_id"]
    ok(f"Session started: {session_id}")

    return session_id


def wait_for_state(session_id, token, target_states):
    divider("WAITING FOR SCRAPER STATE")

    while True:
        status = api_request(f"/scraper/status/{session_id}", "GET", token=token)
        pprint(status)

        state = status["state"]

        if state in target_states:
            ok(f"Reached state: {state}")
            return state

        if state == "FAILED":
            fail(f"Scraper failed: {status.get('last_error')}")

        print("⏳ Waiting...")
        import time
        time.sleep(2)


from PIL import Image
from io import BytesIO
from rich.console import Console
from rich_pixels import Pixels

console = Console()

def handle_captcha(session_id, token):
    divider("CAPTCHA REQUIRED")

    print("👉 Fetching captcha image...")

    req = urllib.request.Request(
        f"{API_URL}/scraper/captcha/{session_id}",
        method="GET"
    )
    req.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(req) as resp:
        img_bytes = resp.read()
        ok("Captcha image fetched")

    try:
        # Load image from bytes
        img = Image.open(BytesIO(img_bytes)).convert("RGB")

        # Resize for terminal width (adjust if needed)
        max_width = 80
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height))

        # Render with rich_pixels
        pixels = Pixels.from_image(img)
        console.print(pixels)

    except Exception as e:
        warn(f"Failed to render captcha image: {e}")

    captcha = input("Enter captcha manually: ").strip()

    api_request(
        f"/scraper/captcha/{session_id}",
        "POST",
        {"captcha": captcha},
        token
    )

    ok("Captcha submitted")

def get_case_list(session_id, token):
    divider("FETCHING CASE LIST")

    response = api_request(f"/scraper/list/{session_id}", "GET", token=token)

    pprint(response)
    cases = response.get("cases", [])
    ok(f"Total cases returned: {len(cases)}")

    return cases

def test_select_multiple(session_id, token, cases):
    divider("TESTING SELECT-MULTIPLE")

    available_indices = [c["index"] for c in cases]

    random.shuffle(available_indices)

    selected = available_indices[: min(3, len(available_indices))]

    print(f"Randomly selecting case indices: {selected}")

    result = api_request(
        f"/scraper/select-multiple/{session_id}",
        "POST",
        {"case_indices": selected},
        token
    )

    pprint(result)

    ok(f"Preview returned {len(result['cases'])} cases")

    # Simulate frontend mutation
    if len(selected) > 1:
        removed = selected.pop()
        print(f"Simulating removal of index {removed}")

    return selected

def test_save_multiple(session_id, token, final_indices):
    divider("TESTING SAVE-MULTIPLE")

    print(f"Saving indices: {final_indices}")

    result = api_request(
        f"/scraper/save-multiple/{session_id}?workspace_id={WORKSPACE_ID}",
        "POST",
        {"case_indices": final_indices},
        token
    )

    pprint(result)

    ok(f"Saved {result['saved_count']} cases")


def main():
    token = login()

    session_id = start_party_search(token)

    state = wait_for_state(session_id, token, ["CAPTCHA_REQUIRED", "CASE_LIST_LOADED"])

    if state == "CAPTCHA_REQUIRED":
        handle_captcha(session_id, token)
        wait_for_state(session_id, token, ["CASE_LIST_LOADED"])

    cases = get_case_list(session_id, token)

    if not cases:
        fail("No cases found — cannot continue")

    # selected = test_select_multiple(session_id, token, len(cases))
    selected = test_select_multiple(session_id, token, cases)

    test_save_multiple(session_id, token, selected)

    divider("MULTI-CASE FLOW VERIFIED SUCCESSFULLY")


if __name__ == "__main__":
    main()