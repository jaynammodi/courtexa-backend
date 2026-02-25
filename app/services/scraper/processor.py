# processor.py
import re
import html
import bleach
from bleach.css_sanitizer import CSSSanitizer
from bs4 import BeautifulSoup
from datetime import datetime

DATE_FORMATS = [
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%m-%d-%Y",
    "%m/%d/%Y",
]

DATE_KEYWORDS = (
    "date",
    "hearing",
    "filing",
    "registration",
    "dob",
)

def maybe_normalize_value(key, value):
    v = clean_text(value)

    if any(k in key.lower() for k in DATE_KEYWORDS):
        return normalize_date(v)

    return v

def normalize_date(value: str | None):
    if not value:
        return None

    value = value.strip()

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    return value  # fallback: keep original if unknown

def clean_text(text):
    if not text:
        return ""
    return " ".join(text.split())

def parse_kv_table(soup, css_class):
    """Parses standard Key-Value tables (like Case Details, Status)."""
    data = {}
    
    # Try direct select
    rows = soup.select(f'.{css_class} tr')
    
    # Fallback to ID if class select fails (sometimes eCourts uses IDs that look like classes)
    if not rows and 'id=' in css_class:
        t = soup.find('table', id=css_class.replace('#',''))
        if t: rows = t.find_all('tr')
    
    # Standard fallback
    if not rows:
        t = soup.find('table', class_=css_class)
        if t: rows = t.find_all('tr')

    if not rows:
        return {}

    for row in rows:
        cells = row.find_all('td')
        # 4-column layout: Key | Value | Key | Value
        # if len(cells) == 4:
        #     data[clean_text(cells[0].text).rstrip(':')] = clean_text(cells[1].text)
        #     data[clean_text(cells[2].text).rstrip(':')] = clean_text(cells[3].text)
        if len(cells) == 4:
            k1 = clean_text(cells[0].text).rstrip(':')
            v1 = maybe_normalize_value(k1, cells[1].text)

            k2 = clean_text(cells[2].text).rstrip(':')
            v2 = maybe_normalize_value(k2, cells[3].text)

            data[k1] = v1
            data[k2] = v2
        # 2-column layout: Key | Value
        # elif len(cells) == 2:
        #     data[clean_text(cells[0].text).rstrip(':')] = clean_text(cells[1].text)
        elif len(cells) == 2:
            k = clean_text(cells[0].text).rstrip(':')
            v = maybe_normalize_value(k, cells[1].text)
            data[k] = v
        # Special case for "Court number and Judge" which often spans colspan
        elif len(cells) == 1:
             # Check if it's a header or a value
             pass 
             
    return data

def parse_simple_table(soup, css_class, headers):
    """Parses simple list tables like Acts."""
    data = []
    rows = soup.select(f'.{css_class} tr')
    
    if not rows:
        t = soup.find('table', class_=css_class)
        if t: rows = t.find_all('tr')

    # Skip header row usually
    for row in rows:
        cells = row.find_all('td')
        if not cells: continue # Skip th rows
        
        row_dict = {}
        for i, cell in enumerate(cells):
            if i < len(headers):
                row_dict[headers[i]] = clean_text(cell.text)
        
        if row_dict:
            data.append(row_dict)
    return data

def parse_party_text(soup, css_class):
    """Parses Petitioner/Respondent text blocks."""
    table = soup.select_one(f'.{css_class}')
    if not table:
        table = soup.find('table', class_=css_class)
    
    if not table: return "N/A"
    
    # Replace <br> with newlines
    for br in table.find_all("br"):
        br.replace_with("\n")
        
    return clean_text(table.get_text(separator=" ", strip=True))

def parse_history_row(cells, business_text=""):
    """Helper to structure a single history row."""
    # Columns: 0=Judge, 1=BusinessDate(Link), 2=HearingDate, 3=Purpose
    if len(cells) < 4: return None
    
    return {
        'judge': clean_text(cells[0].text),
        'business_date': normalize_date(clean_text(cells[1].text)),
        'hearing_date': normalize_date(clean_text(cells[2].text)),
        'purpose': clean_text(cells[3].text),
        'business_update': business_text 
    }

def parse_history_row_text(cells, business_text=""):
    """Helper to structure a single history row from already extracted text."""
    if len(cells) < 4: return None
    
    # Assuming cells is [Hearing Date, Business Date, Purpose, Judge, Business Status]
    # Use consistent keys
    return {
        'judge': clean_text(cells[3]),
        'business_date': normalize_date(clean_text(cells[1])),
        'hearing_date': normalize_date(clean_text(cells[0])),
        'purpose': clean_text(cells[2]),
        'business_update': clean_text(cells[4]) if len(cells) > 4 else business_text
    }

def sanitize_html(html_fragment):
    """
    Accepts raw HTML fragment from eCourts
    Returns sanitized HTML safe for frontend rendering
    """
    if not html_fragment:
        return ""

    # decode escaped HTML
    html_fragment = html.unescape(html_fragment)

    # wrap fragment (API returns inner HTML)
    wrapped_html = f'<div id="sanitized_content">{html_fragment}</div>'

    soup = BeautifulSoup(wrapped_html, "html.parser")
    container = soup.select_one("#sanitized_content")

    if not container:
        return ""

    # remove scripts & iframes entirely
    for tag in container.find_all(["script", "iframe"]):
        tag.decompose()

    # remove JS attributes + neutralize links
    for tag in container.find_all(True):
        for attr in list(tag.attrs):
            if attr.startswith("on"):  # onclick, onmouseover, etc
                del tag.attrs[attr]

        if tag.name == "a":
            tag.attrs.pop("href", None)
            tag.attrs["style"] = tag.attrs.get(
                "style", ""
            ) + ";pointer-events:none;cursor:default;"

    # enforce table class globally (fixes broken formatting)
    for table in container.find_all("table"):
        classes = table.get("class", [])
        if "table" not in classes:
            classes.insert(0, "table")
        table["class"] = classes

    raw_html = str(container)

    # final bleach sanitize (preserve layout)
    css_sanitizer = CSSSanitizer(
        allowed_css_properties=[
            "text-align",
            "font-weight",
            "font-style",
            "text-decoration",
            "color",
            "background-color",
            "border",
            "border-collapse",
            "border-spacing",
            "width",
            "height",
            "padding",
            "margin",
            "vertical-align",
            "font-size"
        ]
    )
    clean_html = bleach.clean(
        raw_html,
        tags=[
            "div","span","table","thead","tbody","tr","td","th",
            "p","b","strong","i","u","br","h2","h3","label","em","a",
            "font", "center"
        ],
        attributes={
            "*": [
                "class","style","id",
                "align","colspan","rowspan","width","border","scope",
                "cellpadding", "cellspacing" 
            ]
        },
        css_sanitizer=css_sanitizer,
        strip=True
        
    )

    return clean_html

def extract_css_links(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    links = []
    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href")
        if href:
            links.append(href)
    return links

def parse_onclick_args(onclick_text):
    """Extracts arguments from a JS function call like func('arg1', 'arg2')."""
    if not onclick_text: return []
    match = re.search(r"\((.*?)\)", onclick_text)
    if not match: return []
    
    # Split by comma but handle potential quotes
    # Simple split might fail if args contain commas, but eCourts args usually don't
    args = [arg.strip().strip("'").strip('"') for arg in match.group(1).split(',')]
    return args

def parse_case_metadata(html_content):
    """
    Parses only the metadata sections (Details, Status, Parties, Acts, FIR).
    Skips History and Orders tables.
    """
    if not html_content: return {}
    
    # decode escaped HTML
    html_fragment = html.unescape(html_content)
    # wrap fragment
    wrapped_html = f'<div id="case_data">{html_fragment}</div>'
    soup = BeautifulSoup(wrapped_html, "html.parser")
    
    heading_el = soup.select_one('#chHeading')
    court_heading = clean_text(heading_el.text) if heading_el else None

    return {
        "court_heading": court_heading,
        "case_details": parse_kv_table(soup, "case_details_table"),
        "status": parse_kv_table(soup, "case_status_table"),
        "petitioner": parse_party_text(soup, "Petitioner_Advocate_table"),
        "respondent": parse_party_text(soup, "Respondent_Advocate_table"),
        "acts": parse_simple_table(soup, "acts_table", ["act", "section"]),
        "fir_details": parse_kv_table(soup, "FIR_details_table"),
    }

def parse_full_case_data(html_content):
    """
    Parses the raw HTML into a structured dictionary matching the reference CLI output.
    Returns full data including History and Orders.
    """
    if not html_content: return {}
    
    # Reuse metadata parsing
    data = parse_case_metadata(html_content)
    
    # Need soup again for History/Orders (optimization: could return soup from metadata parser, but HTML parse is fast enough)
    html_fragment = html.unescape(html_content)
    wrapped_html = f'<div id="case_data">{html_fragment}</div>'
    soup = BeautifulSoup(wrapped_html, "html.parser")
    
    data["history_rows"] = []
    data["orders"] = []
    
    # Parse History Table for Business Logic
    hist_table = soup.find('table', class_='history_table')
    if hist_table:
        for row in hist_table.find_all('tr'):
            cols = row.find_all('td')
            if len(cols) < 4: continue
            
            h_row = {
                "judge": clean_text(cols[0].text),
                "business_date": normalize_date(clean_text(cols[1].text)),
                "hearing_date": normalize_date(clean_text(cols[2].text)),
                "purpose": clean_text(cols[3].text),
                "business_link_args": None
            }
            
            link = cols[1].find('a')
            if link and 'viewBusiness' in link.get('onclick', ''):
                h_row['business_link_args'] = parse_onclick_args(link['onclick'])
                
            data["history_rows"].append(h_row)

    # Parse Orders
    orders_table = soup.find('table', class_='order_table')
    if orders_table:
        for row in orders_table.find_all('tr'):
            cols = row.find_all('td')
            # Check length AND ensure it's not a header row 
            if len(cols) < 3: continue
            
            # Simple check: if first col text is "Order Number", skip
            if "Order" in cols[0].text and "Number" in cols[0].text:
                continue
            
            # Order Number | Date | Order Details (Link)
            o_row = {
                "order_no": clean_text(cols[0].text),
                "order_date": normalize_date(clean_text(cols[1].text)),
                "details": clean_text(cols[2].text),
                "pdf_link_args": None
            }
            
            # Find the best PDF link 
            best_args = None
            links = row.find_all('a', onclick=re.compile(r'displayPdf'))
            
            for link in links:
                args = parse_onclick_args(link['onclick'])
                if args and len(args) >= 4:
                    best_args = args
                    break 
            
            if best_args:
                o_row['pdf_link_args'] = best_args
            
            data["orders"].append(o_row)

    return data
