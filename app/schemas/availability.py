from pydantic import BaseModel
from typing import List, Dict, Any


class AvailabilityOut(BaseModel):
    slot_minutes: int
    buffer_minutes: int
    weekly: List[Dict[str, Any]]
    blackout_dates: List[str]

    class Config:
        from_attributes = True