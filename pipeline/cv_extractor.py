"""
Extraccion de CV -> JSON estructurado usando un modelo :free de OpenRouter.
"""
import os
from pathlib import Path
from pydantic import BaseModel, ValidationError

from pipeline.llm_client import call_llm_json

PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_cv.txt"


class ExtractedProfile(BaseModel):
    skills: list[str] = []
    years_experience_by_skill: dict[str, float] = {}
    seniority: str = "mid"
    equivalent_roles: list[str] = []
    languages: list[str] = []
    certifications: list[str] = []


def extract_cv(cv_text: str) -> dict:
    model = os.environ.get("OPENROUTER_MODEL_EXTRACTION", "minimax/minimax-m2.7:free")
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(cv_text=cv_text)

    raw_json = call_llm_json(model, prompt)
    try:
        validated = ExtractedProfile(**raw_json)
    except ValidationError:
        raw_json = call_llm_json(model, prompt, retry_on_parse_error=False)
        validated = ExtractedProfile(**raw_json)
    return validated.model_dump()
