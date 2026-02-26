import json
import os
from pprint import pprint
# Ensure app path
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.services.scraper.processor import parse_full_case_data

if __name__ == "__main__":
    with open("debug_html.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    data = parse_full_case_data(html_content)
    print(json.dumps(data, indent=2))
