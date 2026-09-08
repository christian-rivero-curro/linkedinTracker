"""
Extraccion de CV -> JSON estructurado usando un modelo :free de OpenRouter.
"""
import os
from pathlib import Path
from pydantic import BaseModel, ValidationError

from pipeline.llm_client import call_llm_json

PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_cv.txt"
DEFAULT_EXTRACTION_MODEL = "inclusionai/ling-3.0-flash-fin:free"
DEPRECATED_MODELS = {
    "minimax/minimax-m3:free",
    "minimax/minimax-m2.7:free",
    "minimax/minimax-m2.5:free",
}


class ExtractedProfile(BaseModel):
    skills: list[str] = []
    years_experience_by_skill: dict[str, float] = {}
    seniority: str = "mid"
    equivalent_roles: list[str] = []
    languages: list[str] = []
    certifications: list[str] = []


def _resolve_model_env(name: str, default: str) -> str:
    """
    Lee una variable de entorno de modelo de OpenRouter, tratando valores
    vacios, solo con espacios o modelos descontinuados/inactivos como si no estuvieran definidos.
    """
    value = os.environ.get(name, "").strip()
    if not value or value in DEPRECATED_MODELS:
        return default
    return value


def extract_cv(cv_text: str) -> dict:
    model = _resolve_model_env("OPENROUTER_MODEL_EXTRACTION", DEFAULT_EXTRACTION_MODEL)
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(cv_text=cv_text)

    raw_json = call_llm_json(model, prompt)
    try:
        validated = ExtractedProfile(**raw_json)
    except ValidationError:
        raw_json = call_llm_json(model, prompt, retry_on_parse_error=False)
        validated = ExtractedProfile(**raw_json)
    return validated.model_dump()
