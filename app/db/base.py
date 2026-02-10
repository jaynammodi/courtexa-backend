from app.db.base_class import Base

# import all models so Alembic sees them
from app.models.user import User
from app.models.workspace import Workspace
from app.models.membership import WorkspaceMember
from app.models.appointment import Appointment
from app.models.availability import WorkspaceAvailability
from app.models.case import Case, CaseParty, CaseAct, CaseHistory

__all__ = ["Base"]