import json
from bs4 import BeautifulSoup

def parse_options_html(content: str):
    """Parses <option> tags from a select element HTML string or JSON response."""
    html_to_parse = content
    
    # Try JSON extraction first
    try:
        if isinstance(content, str) and (content.strip().startswith('{') or content.strip().startswith('"')):
            # eCourts sometimes returns double encoded or just JSON
            # Clean potential artifacts if it's a dirty string
            clean_content = content
            if content.startswith('"') and content.endswith('"'):
                 clean_content = json.loads(content) # Decode one level if it's a stringified json
            
            # If it's a dict after loading (or if it was a json string)
            if isinstance(clean_content, str):
                 try:
                    json_data = json.loads(clean_content)
                 except:
                    json_data = {}
            else:
                 json_data = clean_content

            if isinstance(json_data, dict):
                 for key in ['district_list', 'court_complex_list', 'data_list', 'est_list', 'cino_data', 'party_data', 'adv_data']:
                     if key in json_data:
                         html_to_parse = json_data[key]
                         break
    except Exception:
        pass # Fallback to parsing as raw HTML

    soup = BeautifulSoup(html_to_parse, 'html.parser')
    options = []
    
    for opt in soup.find_all('option'):
        val = opt.get('value')
        text = opt.text.strip()
        
        # Clean artifacts like "<\/option>" if any leaked
        if "<" in text: text = text.split("<")[0]
        
        if val and val != "0" and "Select" not in text:
            options.append({"value": val, "text": text})
            
    return options
