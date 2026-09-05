from pydantic import BaseModel
from typing import Optional


class OnboardingRequest(BaseModel):
    raw_cv_text: str
    location_preference: Optional[str] = None
    remote_preference: str = "any"
    role_family: list[str] = []
    min_salary: Optional[int] = None
    excluded_keywords: list[str] = []


class JobStatusUpdate(BaseModel):
    status: str
