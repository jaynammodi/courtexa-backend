import re
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from app.scraper.structs import (
    CaseSchema, CasePartySchema, CaseActSchema, CaseHistorySchema,
    CaseCourtSchema, CaseSummarySchema, CaseDetailsSchema, CaseStatusSchema, CaseOrderSchema,
    CaseFIRSchema
)

def parse_date(date_str: str) -> Optional[date]:
    """Parses DD-MM-YYYY or DD/MM/YYYY."""
    if not date_str or date_str.lower() in ["nan", "na", "", "null"]:
        return None
    
    formats = ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %B %Y"]
    
    # Handle "04th March 2024" -> "04 March 2024"
    # Remove st, nd, rd, th suffix from day
    clean_date = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str.strip(), flags=re.IGNORECASE)
    
    for fmt in formats:
        try:
            return datetime.strptime(clean_date, fmt).date()
        except ValueError:
            continue
    return None

def transform_to_schema(scraped_data: Dict[str, Any], cino: str) -> CaseSchema:
    details = scraped_data.get("case_details", {})
    status = scraped_data.get("status", {})
    
    # --- 1. Map Case Details ---
    case_details_obj = CaseDetailsSchema(
        case_type=details.get("Case Type"),
        filing_number=details.get("Filing Number"),
        filing_date=parse_date(details.get("Filing Date")),
        registration_number=details.get("Registration Number"),
        registration_date=parse_date(details.get("Registration Date"))
    )
    
    # --- 2. Map Status ---
    first_hearing = parse_date(status.get("First Hearing Date"))
    decision_date = parse_date(status.get("Decision Date"))
    
    case_status_text = status.get("Case Status")
    nature_of_disposal = status.get("Nature of Disposal")
    
    if nature_of_disposal:
        case_status_text = f"{case_status_text} - {nature_of_disposal}"
        
    case_status_obj = CaseStatusSchema(
        first_hearing_date=first_hearing,
        next_hearing_date=parse_date(status.get("Next Hearing Date")) or parse_date(status.get("Next Date")),
        last_hearing_date=None, 
        decision_date=decision_date,
        case_stage=status.get("Case Stage"),
        case_status_text=case_status_text,
        judge=status.get("Court Number and Judge") or status.get("Coram") or status.get("Judge")
    )
    
    # --- 3. Map Parties ---
    parties = []
    
    # Helper to parse raw text blob
    def parse_parties(raw_text: str, is_petitioner: bool):
        if not raw_text or raw_text == "N/A":
            return
        
        # Regex to split by "1) ", "2) " etc.
        # Pattern: look for digit + ) + space
        # We need to lookahead or split. 
        # e.g. "1) Name Adv xxx 2) Name2" 
        
        # Add a sentinel for the first one if it doesn't start with 1) (sometimes it doesn't)
        # But usually eCourts adds it.
        
        # Strategy: 
        # 1. Normalize line endings
        # 2. Split by regex `\d+\)`
        
        parts = re.split(r'\d+\)', raw_text)
        
        # The first part might be empty if text starts with "1)"
        cleaned_parts = [p.strip() for p in parts if p.strip()]
        
        # If no split happened (no numbers), treat as single party
        if not cleaned_parts:
             cleaned_parts = [raw_text.strip()]
             
        for p_text in cleaned_parts:
            # Extract Advocate
            # Pattern: "Name... Advocate - AdvName"
            # Or "Name... Advocate-AdvName"
            # Or "Name... Adv. Name"
            
            advocate_name = None
            clean_name = p_text
            
            # Simple splitter for "Advocate"
            if "Advocate" in p_text:
                splits = re.split(r'Advocate\s*[-–:]?\s*', p_text, flags=re.IGNORECASE)
                if len(splits) > 1:
                    clean_name = splits[0].strip()
                    advocate_name = splits[1].strip()
            
            # Special case cleanup for trailing "Adv" or similar?
            # For now, keep it simple.
            
            # Remove any trailing "1)", "2)" if regex missed something? No, split handles it.
            
            parties.append(CasePartySchema(
                is_petitioner=is_petitioner,
                name=clean_name,
                advocate=advocate_name,
                raw_text=p_text,
                role="Petitioner" if is_petitioner else "Respondent"
            ))

    # Petitioner
    parse_parties(scraped_data.get("petitioner", ""), True)
        
    # Respondent
    parse_parties(scraped_data.get("respondent", ""), False)

    # --- 4. Map Acts ---
    acts_data = scraped_data.get("acts", [])
    acts = []
    for act in acts_data:
        acts.append(CaseActSchema(
            act_name=act.get("act", "Unknown"),
            section=act.get("section")
        ))
        
    # --- 5. Map History ---
    history_rows = scraped_data.get("history_rows", [])
    history = []
    for row in history_rows:
        history.append(CaseHistorySchema(
            business_date=parse_date(row.get("business_date")),
            hearing_date=parse_date(row.get("hearing_date")),
            purpose=row.get("purpose"),
            judge=row.get("judge"),
            notes=row.get("business_update")
        ))

    # --- 6. Map Orders ---
    orders_data = scraped_data.get("orders", [])
    orders = []
    for row in orders_data:
        # We don't construct the full PDF link here, that happens in flows/routes
        # But we can map the basic details
        orders.append(CaseOrderSchema(
            order_no=row.get("order_no"),
            date=row.get("date"),
            details=row.get("details"),
            pdf_filename=row.get("pdf_filename") # This will be populated in flows.py
        ))

    # --- 7. Construct Summary & Title ---
    
    # Generate Clean Title
    # Strategy: "Petitioner vs Respondent, et al."
    # If multiple petitioners: "Petitioner 1, Petitioner 2, et al."
    
    pets = [p for p in parties if p.is_petitioner]
    resps = [p for p in parties if not p.is_petitioner]
    
    def format_party_list(p_list):
        names = [p.name for p in p_list if p.name]
        if not names: return "Unknown"
        if len(names) > 2:
            return f"{names[0]}, {names[1]} et al."
        return ", ".join(names)

    pet_title = format_party_list(pets)
    resp_title = format_party_list(resps)
    
    full_title = f"{pet_title} vs {resp_title}"
    
    # Generate Clean Summary (Sanitized strings)
    # Join all names with commas, no numbering
    pet_summary = ", ".join([p.name for p in pets])
    resp_summary = ", ".join([p.name for p in resps])

    summary_obj = CaseSummarySchema(
        petitioner=pet_summary,
        respondent=resp_summary,
        short_title=full_title
    )
    
    fir_data = scraped_data.get("fir_details", {})
    fir_obj = None
    if fir_data:
        fir_obj = CaseFIRSchema(
            police_station=fir_data.get("Police Station"),
            fir_number=fir_data.get("FIR Number"),
            year=fir_data.get("Year")
        )

    # --- 8. Final Object ---
    
    # Internal Status Logic
    internal_status = "active"
    
    status_text_clean = (case_status_text or "").lower()
    disposal_nature = (nature_of_disposal or "").lower()
    
    if "disposed" in status_text_clean or "decided" in status_text_clean or \
       "disposed" in disposal_nature or "decided" in disposal_nature:
        internal_status = "disposed"

    # Court Info
    court_obj = CaseCourtSchema(
        name=scraped_data.get("court_heading"),
        bench=status.get("Court Number and Judge") or status.get("Coram") or status.get("Judge")
    )

    return CaseSchema(
        cino=cino,
        title=summary_obj.short_title or cino,
        internal_status=internal_status,
        court=court_obj,
        case_details=case_details_obj,
        status=case_status_obj,
        fir_details=fir_obj,
        summary=summary_obj,
        parties=parties,
        acts=acts,
        history=history,
        orders=orders,
        meta_source="ecourts",
        meta_source_url=scraped_data.get("meta_url"),
        raw_html=scraped_data.get("raw_html") 
    )
