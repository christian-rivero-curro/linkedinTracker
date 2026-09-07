"""
Extraccion de CV -> JSON estructurado usando un modelo :free de OpenRouter.
"""
import os
from pathlib import Path
from pydantic import BaseModel, ValidationError

from pipeline.llm_client import call_llm_json

PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_cv.txt"
DEFAULT_EXTRACTION_MODEL = "minimax/minimax-m2.7:free"


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
    vacios o solo con espacios como si no estuvieran definidos. Necesario
    porque en GitHub Actions una variable de repo (`vars.*`) sin configurar
    se pasa igualmente como env var, pero con cadena vacia: os.environ.get()
    con default NO cubre ese caso (la clave existe, solo que vacia), y eso
    provocaba enviar model="" a la API de OpenRouter (400 Bad Request).
    """
    value = os.environ.get(name, "").strip()
    return value if value else default


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
