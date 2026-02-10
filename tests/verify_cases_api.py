import urllib.request
import urllib.parse
import json
import sys
from pprint import pprint

API_URL = "http://127.0.0.1:8000/api/v1"
WORKSPACE_ID = "20cf75e5-c39c-4adf-a589-cb82b57a677f"

def divider(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

def fail(msg):
    print(f"❌ FAIL: {msg}")

def warn(msg):
    print(f"⚠️  WARN: {msg}")

def ok(msg):
    print(f"✅ OK: {msg}")

def verify():
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

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.load(resp)
            token = data["access_token"]
            ok("Login successful")
    except Exception as e:
        fail("Login failed")
        if hasattr(e, "read"):
            print(e.read().decode())
        sys.exit(1)

    headers = {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    divider("CASE INDEX API  —  GET /cases")

    req = urllib.request.Request(
        f"{API_URL}/cases?workspace_id={WORKSPACE_ID}",
        method="GET"
    )
    req.add_header("Authorization", headers["Authorization"])

    try:
        with urllib.request.urlopen(req) as resp:
            cases = json.load(resp)
            ok(f"Fetched {len(cases)} cases")
    except Exception as e:
        fail("Failed to fetch case index")
        if hasattr(e, "read"):
            print(e.read().decode())
        return

    if not cases:
        fail("No cases returned — cannot continue verification")
        return

    c = cases[0]
    print("\nSample index row:")
    pprint(c)

    # Index shape validation
    required_index_keys = {
        "id", "cino", "title", "internal_status"
    }

    missing = required_index_keys - c.keys()
    if missing:
        fail(f"Index row missing keys: {missing}")
    else:
        ok("Index row required keys present")

    forbidden_index_keys = {"history", "acts", "parties", "raw_html"}
    leaked = forbidden_index_keys & c.keys()
    if leaked:
        warn(f"Index row leaked heavy fields: {leaked}")
    else:
        ok("Index row does not leak heavy fields")

    case_id = c["id"]

    # ------------------------------------------------------------------
    divider("CASE SUMMARY API  —  GET /cases/{id}/summary")

    req = urllib.request.Request(
        f"{API_URL}/cases/{case_id}/summary",
        method="GET"
    )
    req.add_header("Authorization", headers["Authorization"])

    try:
        with urllib.request.urlopen(req) as resp:
            summary = json.load(resp)
            ok("Fetched case summary")
    except Exception as e:
        fail("Failed to fetch case summary")
        if hasattr(e, "read"):
            print(e.read().decode())
        return

    print("\nCase summary:")
    pprint(summary)

    summary_required = {
        "id", "cino", "title",
        "petitioner", "respondent",
        "internal_status"
    }

    missing = summary_required - summary.keys()
    if missing:
        fail(f"Summary missing keys: {missing}")
    else:
        ok("Summary required keys present")

    if summary["id"] != case_id:
        fail("Summary ID mismatch with index ID")
    else:
        ok("Summary ID matches index")

    # ------------------------------------------------------------------
    divider("FULL CASE API  —  GET /cases/{id}")

    req = urllib.request.Request(
        f"{API_URL}/cases/{case_id}",
        method="GET"
    )
    req.add_header("Authorization", headers["Authorization"])

    try:
        with urllib.request.urlopen(req) as resp:
            full = json.load(resp)
            ok("Fetched full case")
    except Exception as e:
        fail("Failed to fetch full case")
        if hasattr(e, "read"):
            print(e.read().decode())
        return

    print("\nFull case (keys only):")
    pprint(sorted(full.keys()))

    full_required = {
        "id", "workspace_id", "cino", "title",
        "court", "parties", "acts", "history",
        "case_details", "status", "internal_status",
        "created_at", "updated_at"
    }

    missing = full_required - full.keys()
    if missing:
        fail(f"Full case missing keys: {missing}")
    else:
        ok("Full case required keys present")

    if full["id"] != case_id:
        fail("Full case ID mismatch")
    else:
        ok("Full case ID matches index & summary")

    # ------------------------------------------------------------------
    divider("RELATIONAL SANITY CHECKS")

    try:
        p_count = len(full["parties"]["petitioners"])
        r_count = len(full["parties"]["respondents"])
        ok(f"Parties loaded (P={p_count}, R={r_count})")
    except Exception:
        fail("Parties structure invalid")

    ok(f"Acts count: {len(full['acts'])}")
    ok(f"History entries: {len(full['history'])}")

    divider("VERIFICATION COMPLETE — READY FOR FRONTEND")

if __name__ == "__main__":
    verify()