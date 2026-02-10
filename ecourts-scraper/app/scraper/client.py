import re
import time
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, Tuple
from app.config import settings

# Use settings for Base URL
BASE_URL = settings.ECOURTS_BASE_URL

# HEADERS matching the working CLI script exactly
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Mobile Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'en-US,en-IN;q=0.9,en;q=0.8',
    'Origin': 'https://services.ecourts.gov.in',
    'Referer': 'https://services.ecourts.gov.in/',
    'X-Requested-With': 'XMLHttpRequest',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' 
}

def extract_token_from_json(response):
    try:
        data = response.json()
        token = data.get('token') or data.get('app_token')
        if token:
            print(f"DEBUG: Extracted new token: {token[:10]}...")
        return token
    except:
        return None

def clean_text(text):
    if not text: return ""
    return " ".join(text.split())

class ECourtsClient:
    def __init__(self, cookies: Optional[Dict] = None, current_token: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        if cookies:
            self.session.cookies.update(cookies)
        self.current_token = current_token

    def get_cookies(self) -> Dict:
        return self.session.cookies.get_dict()

    def _update_token(self, response):
        """Internal method to update token if present in response."""
        new_token = extract_token_from_json(response)
        if new_token:
            self.current_token = new_token
            print(f"DEBUG: Token updated in client to: {self.current_token[:10]}...")

    def _post(self, endpoint, data):
        """Wrapper for POST requests with auto token injection and update."""
        url = f"{BASE_URL}/?p={endpoint}"
        
        # Inject current token
        if 'app_token' not in data and self.current_token:
            data['app_token'] = self.current_token
        if 'ajax_req' not in data:
            data['ajax_req'] = 'true'

        print(f"DEBUG: POST {endpoint} | Token: {data.get('app_token')[:10] if data.get('app_token') else 'None'}")
        
        resp = self.session.post(url, data=data)
        self._update_token(resp)
        return resp

    def get_initial_token(self) -> Tuple[Optional[str], str]:
        """Loads homepage to get the first session token."""
        url = f"{BASE_URL}/?p=casestatus/index"
        
        # Remove ajax headers for page load
        page_headers = self.session.headers.copy()
        if 'X-Requested-With' in page_headers: del page_headers['X-Requested-With']
        if 'Content-Type' in page_headers: del page_headers['Content-Type']
        
        print(f"DEBUG: GET Initial {url}")
        resp = self.session.get(url, headers=page_headers)
        
        # Scrape token
        soup = BeautifulSoup(resp.text, 'html.parser')
        token_input = soup.find('input', {'name': 'app_token'})
        if token_input: 
            self.current_token = token_input['value']
        else:
            match = re.search(r'app_token\s*=\s*["\']([^"\']+)["\']', resp.text)
            if match: self.current_token = match.group(1)
            
        print(f"DEBUG: Initial Token: {self.current_token[:10] if self.current_token else 'None'}")
        return self.current_token, resp.text

    def get_captcha(self) -> bytes:
        """Triggers generation and downloads image."""
        self._post('casestatus/getCaptcha', {})
        
        timestamp = int(time.time() * 1000)
        img_url = f"{BASE_URL}/vendor/securimage/securimage_show.php?{timestamp}"
        
        # Download headers
        img_headers = self.session.headers.copy()
        if 'Content-Type' in img_headers: del img_headers['Content-Type']
        if 'X-Requested-With' in img_headers: del img_headers['X-Requested-With']
        
        print(f"DEBUG: GET Captcha Image")
        # Trigger
        self.session.get(img_url, headers=img_headers)
        # Download
        resp = self.session.get(img_url, headers=img_headers)
        
        # Sometimes eCourts sends text/html error instead of image
        if 'text/html' in resp.headers.get('Content-Type', ''):
             pass

        return resp.content

    def get_districts(self, state_code):
        return self._post('casestatus/fillDistrict', {'state_code': state_code})

    def get_complexes(self, state_code, dist_code):
        return self._post('casestatus/fillcomplex', {'state_code': state_code, 'dist_code': dist_code})

    def set_data(self, state, dist, complex_code):
        # Ensure complex code suffix is correct
        formatted_code = complex_code if '@' in complex_code else f"{complex_code}@1@N"
        return self._post('casestatus/set_data', {
            'complex_code': formatted_code,
            'selected_state_code': state,
            'selected_dist_code': dist,
            'selected_est_code': 'null'
        })
    
    def search_party(self, params):
        return self._post('casestatus/submitPartyName', params)

    def search_advocate(self, params):
        return self._post('casestatus/submitAdvName', params)

    def search_cnr(self, params):
        return self._post('cnr_status/searchByCNR', params)

    def view_history(self, params):
        """Used when selecting a specific case from Party/Advocate search results."""
        return self._post('home/viewHistory', params)

    def view_business(self, params):
        resp = self._post('home/viewBusiness', params)
        try:
            data = resp.json()
        except:
            return "N/A"
            
        html_content = data.get('data_list', '')
        
        if not html_content: return "N/A"
        
        soup = BeautifulSoup(html_content, 'html.parser')
        # Logic to find the correct business date column
        business_td = soup.find(lambda tag: tag.name == "td" and "Business" in tag.text and "Date" not in tag.text)
        
        result_text = clean_text(soup.text)
        if business_td:
            row = business_td.find_parent('tr')
            cells = row.find_all('td')
            if len(cells) >= 3:
                result_text = clean_text(cells[2].text)
        return result_text

    def display_pdf(self, params):
        """Triggers PDF generation on server."""
        return self._post('home/display_pdf', params)

    def get_pdf_bytes(self):
        """Downloads the generated PDF using session ID."""
        sess_id = self.session.cookies.get('SERVICES_SESSID') or self.session.cookies.get('PHPSESSID')
        if not sess_id:
             c = self.session.cookies.get_dict()
             sess_id = c.get('SERVICES_SESSID') or c.get('PHPSESSID')
             
        if not sess_id: return None

        pdf_url = f"{BASE_URL}/reports/{sess_id}.pdf"
        pdf_headers = self.session.headers.copy()
        if 'X-Requested-With' in pdf_headers: del pdf_headers['X-Requested-With']
        
        resp = self.session.get(pdf_url, headers=pdf_headers)
        if resp.status_code == 200 and b'%PDF' in resp.content:
            return resp.content
        return None
