import uuid
import re
from datetime import datetime, timedelta, date, UTC
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from app.models.membership import WorkspaceMember, WorkspaceRole
from app.models.appointment import Appointment, AppointmentStatus, AppointmentType
from app.core.security import get_password_hash
from app.models.case import Case, CaseParty, CaseAct, CaseHistory

def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def parse_date(d_str):
    if not d_str:
        return None
    if isinstance(d_str, (date, datetime)):
        return d_str
    # formats seen: "YYYY-MM-DD", "DD-MM-YYYY"
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(d_str, fmt).date()
        except ValueError:
            continue
    return None

def run():
    db = SessionLocal()

    # ---------- USER ----------
    email = "lawyer@demo.com"
    user = db.query(User).filter(User.email == email).first()

    if not user:
        user = User(
            email=email,
            full_name="Demo Lawyer",
            password_hash=get_password_hash("password123"),
            is_active=True,
            is_superadmin=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print("Created user")

    # ---------- WORKSPACE ----------
    name = "Demo Workspace"
    slug = slugify(name)

    workspace = db.query(Workspace).filter(Workspace.slug == slug).first()

    if not workspace:
        workspace = Workspace(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            owner_id=user.id,
        )
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        print("Created workspace")

    # ---------- MEMBERSHIP ----------
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace.id,
        WorkspaceMember.user_id == user.id,
    ).first()

    if not member:
        member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.LAWYER,
            is_active=True,
        )
        db.add(member)
        db.commit()
        print("Created membership")

    # ---------- APPOINTMENTS ----------
    if db.query(Appointment).count() <= 3:
        now = datetime.now(UTC)

        for i in range(5):
            appt = Appointment(
                workspace_id=workspace.id,
                title=f"Consultation — Client {i+1}",
                notes="Initial consult",
                start_at=now + timedelta(days=i, hours=2),
                end_at=now + timedelta(days=i, hours=3),
                type=AppointmentType.client_meeting,
                status=AppointmentStatus.requested,
                requested_by="client",
                client_name=f"Client {i+1}",
                client_email=f"client{i+1}@mail.com",
                client_phone="9999999999",
            )
            db.add(appt)
        db.commit()
        print("Seeded appointments")

    # ---------- CASES ----------
    # Only seed if no cases exist to avoid duplicates
    if db.query(Case).count() == 0:
        print("Seeding cases...")
        today = date.today()
        
        # Mock Data Definition
        mock_cases = [
            {
                "cino": "UTDD010001892025",
                "title": "M/s. Sincure Foils v/s M/s. Krosyl Pharmaceutical Pvt, Ltd.",
                "internal_status": "active",
                "court": {"name": "District and Sessions Court, Daman", "level": "DISTRICT", "bench": "Principal District and Sessions Judge"},
                "case_details": {
                    "case_type": "Execution Application", 
                    "filing_number": "14/2025", 
                    "filing_date": "2025-02-04", 
                    "registration_number": "1/2025", 
                    "registration_date": "2025-02-04"
                },
                "status": {
                    "first_hearing_date": "2025-02-07", "next_hearing_date": "2026-02-03", "last_hearing_date": None,
                    "decision_date": None, "case_stage": "AWAITING NOTICE", "case_status_text": None,
                    "judge": "Principal District and Sessions Judge"
                },
                "parties": {
                    "petitioners": [
                        {"name": "M/s. Sincure Foils", "advocate": "Shri Shehul P. Halpati", "rawText": "1) M/s. Sincure Foils Advocate- Shri Shehul P. Halpati"},
                        {"name": "M/s. Demo Foils", "advocate": "Shri Jay P. Halpati", "rawText": "1) M/s. Sincure Foils Advocate- Shri Shehul P. Halpati"}
                    ],
                    "respondents": [
                        {"name": "M/s. Krosyl Pharmaceutical Pvt, Ltd.", "rawText": "1) M/s. Krosyl Pharmaceutical Pvt, Ltd."}
                    ]
                },
                "acts": [{"act": "Code of Civil Procedure", "sections": ["21", "11"]}],
                "history": [
                    {"business_date": "2026-01-12", "hearing_date": "2026-02-03", "purpose": "AWAITING NOTICE", "notes": "4 Adv S. S. Modasia filed application...", "judge": "Principal District and Sessions Judge"},
                    {"business_date": "2025-12-04", "hearing_date": "2026-01-12", "purpose": "NOTICE", "notes": "Honble P.O is on leave...", "judge": "Principal District and Sessions Judge"},
                    {"business_date": "2025-02-07", "hearing_date": "2025-04-11", "purpose": "NOTICE", "notes": "Execution application filed...", "judge": "Principal District and Sessions Judge"}
                ],
                "meta": {
                    "scraped_at": datetime(2026, 1, 12), "source": "district-court-daman",
                    "raw_html": '<div id="history_cnr">... (HTML Content) ...</div>'
                }
            },
            {
                "cino": "UTDD010003422014",
                "title": "Supreme Company Limited v/s Gopal Bhula and 01 Ors",
                "internal_status": "disposed",
                "court": {"name": "District and Sessions Court, Daman", "level": "DISTRICT", "bench": "Principal District and Sessions Judge"},
                "case_details": {
                    "case_type": "Civil Appeal", 
                    "filing_number": "2/2014", "filing_date": "20-06-2014",
                    "registration_number": "2/2014", "registration_date": "20-06-2014"
                },
                "status": {
                    "first_hearing_date": "24-07-2014", "next_hearing_date": None, "last_hearing_date": "15-12-2023",
                    "decision_date": "15-12-2023", "case_stage": "JUDGMENT", "case_status_text": "Case disposed",
                    "judge": "Principal District and Sessions Judge"
                },
                "parties": {
                    "petitioners": [{"name": "Supreme Company Limited", "advocate": "Alpa C. Rathod", "rawText": "..."}],
                    "respondents": [{"name": "Gopal Bhula and 01 Ors", "rawText": "..."}]
                },
                "acts": [{"act": "CODE OF CIVIL PROCEDURE", "sections": ["96"]}],
                "history": [
                    {"business_date": "2023-12-15", "hearing_date": None, "purpose": "Disposed", "notes": "Judgment pronounced...", "judge": "Principal District and Sessions Judge"},
                    {"business_date": "2014-07-24", "hearing_date": "2014-08-28", "purpose": "APPEARANCE", "notes": "Initial appearance...", "judge": "Principal District and Sessions Judge"}
                ],
                "meta": {"scraped_at": datetime.now(), "source": "ecourts.gov.in"}
            },
            {
                "cino": "UTDD010004112022",
                "title": "M/s. Alpha Traders v/s M/s. Beta Industries",
                "internal_status": "active",
                "court": {"name": "District and Sessions Court, Daman", "level": "DISTRICT", "bench": "Principal District and Sessions Judge"},
                "case_details": {"case_type": "Summary Suit", "filing_number": "112/2022", "filing_date": "2022-09-14", "registration_number": "112/2022", "registration_date": "2022-09-14"},
                "status": {
                    "first_hearing_date": "2022-09-21", "next_hearing_date": today, 
                    "last_hearing_date": None, "decision_date": None, "case_stage": "ARGUMENTS", "case_status_text": None, 
                    "judge": "Principal District and Sessions Judge"
                },
                "parties": {
                    "petitioners": [{"name": "M/s. Alpha Traders", "advocate": "Adv. R. K. Mehta"}],
                    "respondents": [{"name": "M/s. Beta Industries"}]
                },
                "acts": [{"act": "CODE OF CIVIL PROCEDURE", "sections": ["37"]}],
                "history": [
                    {"business_date": "2024-11-20", "hearing_date": today, "purpose": "ARGUMENTS", "notes": "Final arguments...", "judge": "Principal District and Sessions Judge"}
                ]
            },
            {
                "cino": "UTDD010007892023",
                "title": "Ramesh Patel v/s Suresh Patel",
                "internal_status": "active",
                "court": {"name": "District and Sessions Court, Daman", "level": "DISTRICT", "bench": "Principal District and Sessions Judge"},
                "case_details": {"case_type": "Special Civil Suit", "filing_number": "89/2023", "filing_date": "2023-03-11", "registration_number": "89/2023", "registration_date": "2023-03-11"},
                "status": {
                    "first_hearing_date": "2023-03-18", "next_hearing_date": "2026-03-12", "last_hearing_date": None, "decision_date": None, "case_stage": "EVIDENCE", "case_status_text": None, "judge": "Principal District and Sessions Judge"
                },
                "parties": {
                    "petitioners": [{"name": "Ramesh Patel", "advocate": "Adv. S. P. Joshi"}],
                    "respondents": [{"name": "Suresh Patel"}]
                },
                "acts": [{"act": "TRANSFER OF PROPERTY ACT", "sections": ["54"]}],
                "history": [
                    {"business_date": "2026-02-10", "hearing_date": "2026-03-12", "purpose": "EVIDENCE", "notes": "Plaintiff evidence...", "judge": "Principal District and Sessions Judge"}
                ]
            },
            {
                "cino": "UTDD010009332020",
                "title": "Sunita Sharma v/s United India Insurance Co.",
                "internal_status": "disposed",
                "court": {"name": "District and Sessions Court, Daman", "level": "DISTRICT", "bench": "Principal District and Sessions Judge"},
                "case_details": {"case_type": "Motor Accident Claim", "filing_number": "33/2020", "filing_date": "2020-02-19", "registration_number": "33/2020", "registration_date": "2020-02-19"},
                "status": {
                    "first_hearing_date": "2020-03-02", "next_hearing_date": None, "last_hearing_date": "2023-08-17", "decision_date": "2023-08-17", "case_stage": "JUDGMENT", "case_status_text": "Case disposed", "judge": "Principal District and Sessions Judge"
                },
                "parties": {
                    "petitioners": [{"name": "Sunita Sharma", "advocate": "Adv. N. K. Verma"}],
                    "respondents": [{"name": "United India Insurance Co."}]
                },
                "acts": [{"act": "MOTOR VEHICLES ACT", "sections": ["166"]}],
                "history": [
                    {"business_date": "2023-08-17", "hearing_date": None, "purpose": "Disposed", "notes": "Compensation awarded...", "judge": "Principal District and Sessions Judge"}
                ]
            },
            {
                "cino": "UTDD010002452021",
                "title": "State of Daman v/s Anil Desai",
                "internal_status": "disposed",
                "case_details": {"case_type": "Criminal Appeal", "filing_number": "45/2021", "filing_date": "2021-06-03", "registration_number": "45/2021", "registration_date": "2021-06-03"},
                "court": {"name": "District and Sessions Court, Daman", "level": "DISTRICT", "bench": "Principal District and Sessions Judge"},
                "status": {"first_hearing_date": "2021-06-14", "next_hearing_date": None, "last_hearing_date": "2024-01-09", "decision_date": "2024-01-09", "case_stage": "JUDGMENT", "case_status_text": "Appeal dismissed", "judge": "Principal District and Sessions Judge"},
                "parties": {"petitioners": [{"name": "State of Daman", "advocate": "Public Prosecutor"}], "respondents": [{"name": "Anil Desai"}]},
                "acts": [{"act": "INDIAN PENAL CODE", "sections": ["420"]}],
                "history": [{"business_date": "2024-01-09", "hearing_date": None, "purpose": "Disposed", "notes": "Appeal dismissed...", "judge": "Principal District and Sessions Judge"}]
            },
            {
                "cino": "UTDD010006782024",
                "title": "M/s. Orion Cables Pvt. Ltd. v/s M/s. Nova Power Systems",
                "internal_status": "active",
                "court": {"name": "District and Sessions Court, Daman"},
                "case_details": {"case_type": "Commercial Suit", "filing_number": "67/2024", "filing_date": "2024-07-22", "registration_number": "67/2024", "registration_date": "2024-07-22"},
                "status": {"first_hearing_date": "2024-08-05", "next_hearing_date": "2026-02-15", "case_stage": "NOTICE", "judge": "Principal District and Sessions Judge"},
                "parties": {"petitioners": [{"name": "M/s. Orion Cables Pvt. Ltd.", "advocate": "Adv. K. M. Shah"}], "respondents": [{"name": "M/s. Nova Power Systems"}]},
                "acts": [{"act": "COMMERCIAL COURTS ACT", "sections": ["10"]}],
                "history": [{"business_date": "2026-01-10", "hearing_date": "2026-02-15", "purpose": "NOTICE", "notes": "Notice issued...", "judge": "Principal District and Sessions Judge"}]
            },
            {
                "cino": "UTDD010008912024",
                "title": "Ketan Shah v/s Municipal Council, Daman",
                "internal_status": "active",
                "court": {"name": "District and Sessions Court, Daman"},
                "case_details": {"case_type": "Special Civil Application", "filing_number": "91/2024", "filing_date": "2024-10-11", "registration_number": "91/2024", "registration_date": "2024-10-11"},
                "status": {"first_hearing_date": "2024-10-18", "next_hearing_date": today, "case_stage": "INTERIM RELIEF", "judge": "Principal District and Sessions Judge"},
                "parties": {"petitioners": [{"name": "Ketan Shah", "advocate": "Adv. P. R. Desai"}], "respondents": [{"name": "Municipal Council, Daman"}]},
                "acts": [{"act": "CONSTITUTION OF INDIA", "sections": ["226"]}],
                "history": [{"business_date": today - timedelta(days=7), "hearing_date": today, "purpose": "INTERIM RELIEF", "notes": "Application for interim relief...", "judge": "Principal District and Sessions Judge"}]
            },
            {
                "cino": "UTDD010005672023",
                "title": "M/s. Silverline Industries v/s M/s. Deepak Enterprises",
                "internal_status": "active",
                "court": {"name": "District and Sessions Court, Daman"},
                "case_details": {"case_type": "Execution Petition", "filing_number": "56/2023", "filing_date": "2023-11-09", "registration_number": "56/2023", "registration_date": "2023-11-09"},
                "status": {"first_hearing_date": "2023-11-20", "next_hearing_date": today + timedelta(days=1), "case_stage": "NOTICE RETURNABLE", "judge": "Principal District and Sessions Judge"},
                "parties": {"petitioners": [{"name": "M/s. Silverline Industries", "advocate": "Adv. J. M. Thakkar"}], "respondents": [{"name": "M/s. Deepak Enterprises"}]},
                "acts": [{"act": "CODE OF CIVIL PROCEDURE", "sections": ["36"]}],
                "history": [{"business_date": today - timedelta(days=14), "hearing_date": today + timedelta(days=1), "purpose": "NOTICE RETURNABLE", "notes": "Notice returnable today.", "judge": "Principal District and Sessions Judge"}]
            },
            {
                "cino": "UTDD010001232023",
                "title": "Rajiv Kulkarni v/s Anita Kulkarni",
                "internal_status": "active",
                "court": {"name": "District and Sessions Court, Daman"},
                "case_details": {"case_type": "Miscellaneous Civil Application", "filing_number": "12/2023", "filing_date": "2023-01-19", "registration_number": "12/2023", "registration_date": "2023-01-19"},
                "status": {"first_hearing_date": "2023-02-01", "next_hearing_date": today + timedelta(days=7), "case_stage": "ORDERS", "judge": "Principal District and Sessions Judge"},
                "parties": {"petitioners": [{"name": "Rajiv Kulkarni", "advocate": "Adv. S. D. Kulkarni"}], "respondents": [{"name": "Anita Kulkarni"}]},
                "acts": [{"act": "CODE OF CIVIL PROCEDURE", "sections": ["151"]}],
                "history": [{"business_date": today - timedelta(days=3), "hearing_date": today + timedelta(days=7), "purpose": "ORDERS", "notes": "Orders to be pronounced.", "judge": "Principal District and Sessions Judge"}]
            }
        ]

        for mock in mock_cases:
            court = mock.get("court", {})
            cd = mock.get("case_details", {})
            st = mock.get("status", {})
            meta = mock.get("meta", {})
            
            # Create Case
            new_case = Case(
                id=uuid.uuid4(),
                workspace_id=workspace.id,
                cino=mock["cino"],
                title=mock["title"],
                internal_status=mock.get("internal_status", "active"),
                
                # Court
                court_name=court.get("name"),
                court_level=court.get("level"),
                court_bench=court.get("bench"),
                
                # Details
                case_type=cd.get("case_type"),
                filing_number=cd.get("filing_number"),
                filing_date=parse_date(cd.get("filing_date")),
                registration_number=cd.get("registration_number"),
                registration_date=parse_date(cd.get("registration_date")),
                
                # Status
                first_hearing_date=parse_date(st.get("first_hearing_date")),
                next_hearing_date=parse_date(st.get("next_hearing_date")),
                last_hearing_date=parse_date(st.get("last_hearing_date")),
                decision_date=parse_date(st.get("decision_date")),
                case_stage=st.get("case_stage"),
                case_status_text=st.get("case_status_text"),
                judge=st.get("judge"),

                # Meta
                meta_scraped_at=meta.get("scraped_at", datetime.utcnow()) if meta.get("scraped_at") else None,
                meta_source=meta.get("source"),
                raw_html=meta.get("raw_html"),
            )
            
            # Use specific ID for summary fields
            p_text = mock["parties"]["petitioners"][0]["name"] if mock["parties"]["petitioners"] else ""
            r_text = mock["parties"]["respondents"][0]["name"] if mock["parties"]["respondents"] else ""
            
            new_case.summary_petitioner = p_text
            new_case.summary_respondent = r_text
            new_case.summary_short_title = f"{p_text} v/s {r_text}"

            db.add(new_case)
            db.flush() # Get ID

            # Parties
            for p in mock["parties"].get("petitioners", []):
                db.add(CaseParty(case_id=new_case.id, is_petitioner=True, name=p["name"], advocate=p.get("advocate"), raw_text=p.get("rawText")))
            for r in mock["parties"].get("respondents", []):
                db.add(CaseParty(case_id=new_case.id, is_petitioner=False, name=r["name"], advocate=r.get("advocate"), raw_text=r.get("rawText")))

            # Acts
            for a in mock.get("acts", []):
                db.add(CaseAct(case_id=new_case.id, act_name=a["act"], section=", ".join(a.get("sections", []))))

            # History
            for h in mock.get("history", []):
                db.add(CaseHistory(
                    case_id=new_case.id,
                    business_date=parse_date(h.get("business_date")),
                    hearing_date=parse_date(h.get("hearing_date")),
                    purpose=h.get("purpose"),
                    notes=h.get("notes"),
                    judge=h.get("judge"),
                ))
            
            db.commit()
            print(f"Created case: {new_case.cino}")


    db.close()
    print("✅ Seed complete")

if __name__ == "__main__":
    run()