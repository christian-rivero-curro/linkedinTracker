from pydantic import BaseModel
from typing import Optional


class OnboardingRequest(BaseModel):
    raw_cv_text: str
    location_preference: Optional[str] = None
    remote_preference: str = "any"
    role_family: list[str] = []
    min_salary: Optional[int] = None
    excluded_keywords: list[str] = []
    enabled_sources: list[str] = ["linkedin"]


class DiscoveryTriggerRequest(BaseModel):
    source: Optional[str] = "all"


class JobStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = None
