"""
Similitud vectorial + orquestacion de la evaluacion cualitativa por LLM.
"""
import os
import re
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, field_validator

from pipeline.llm_client import call_llm_structured
from pipeline.embeddings import cosine_similarity

PROMPT_PATH = Path(__file__).parent / "prompts" / "evaluate_job.txt"
DEFAULT_SCORING_MODEL = "inclusionai/ling-3.0-flash-fin:free"
DEPRECATED_MODELS = {
    "minimax/minimax-m3:free",
    "minimax/minimax-m2.7:free",
    "minimax/minimax-m2.5:free",
}

BLACKLIST_KEYWORDS = [
    "marketing", "sales", "ventas", "legal", "teacher", "docente",
    "recruiter", "reclutador", "comercial", "abogado",
]

VALID_RECOMMENDATIONS = ("apply", "consider", "skip")


class JobEvaluationSchema(BaseModel):
    """
    Esquema validado por Pydantic para la respuesta de evaluación cualitativa
    del LLM, garantizando tipos limpios y coherentes para evitar errores de scraping/almacenamiento.
    """
    score: int = Field(default=50, ge=0, le=100, description="Puntuación de encaje de 0 a 100")
    salary: str | None = Field(default=None, description="Rango o cifra salarial en texto si se indica, o None")
    pros: list[str] = Field(default_factory=list, description="Lista de puntos a favor")
    cons: list[str] = Field(default_factory=list, description="Lista de puntos en contra o riesgos")
    missing_requirements: list[str] = Field(
        default_factory=list,
        description="Requisitos de la oferta que el perfil no cumple, empezando por el requisito excluyente si lo hay",
    )
    recommendation: Literal["apply", "consider", "skip"] = Field(
        default="consider",
        description="Recomendación final: apply, consider o skip",
    )

    @field_validator("score", mode="before")
    @classmethod
    def parse_score(cls, v):
        if v is None:
            return 50
        if isinstance(v, (int, float)):
            return max(0, min(100, int(round(v))))
        if isinstance(v, str):
            v_clean = v.strip()
            m = re.search(r"\b(\d+)\b", v_clean)
            if m:
                val = int(m.group(1))
                return max(0, min(100, val))
        return 50

    @field_validator("salary", mode="before")
    @classmethod
    def parse_salary(cls, v):
        if v is None:
            return None
        if not isinstance(v, str):
            v = str(v)
        v = v.strip()
        if not v or v.lower() in (
            "null", "none", "no especificado", "no indica",
            "no disponible", "n/a", "na", "no", "desconocido",
            "undefined", "no menciona", "no salarial"
        ):
            return None
        return v

    @field_validator("pros", "cons", "missing_requirements", mode="before")
    @classmethod
    def parse_string_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v_clean = v.strip()
            return [v_clean] if v_clean else []
        if isinstance(v, (list, tuple)):
            cleaned = []
            for item in v:
                if item is None:
                    continue
                s = str(item).strip()
                if s:
                    cleaned.append(s)
            return cleaned
        return []

    @field_validator("recommendation", mode="before")
    @classmethod
    def parse_recommendation(cls, v):
        if isinstance(v, str):
            cleaned = v.strip().lower()
            if cleaned in ("apply", "consider", "skip"):
                return cleaned
            if "skip" in cleaned:
                return "skip"
            if "apply" in cleaned:
                return "apply"
            if "consider" in cleaned:
                return "consider"
        return "consider"


def is_blacklisted(title: str) -> bool:
    title_lower = title.lower()
    return any(kw in title_lower for kw in BLACKLIST_KEYWORDS)


def vector_score(job_embedding: list[float], profile_embedding: list[float]) -> float:
    return cosine_similarity(job_embedding, profile_embedding)


def hard_requirements_score(profile: dict, job: dict) -> float:
    """Funcion deterministica 0-100 que compara ubicacion/remoto/salario minimo."""
    score = 100.0
    remote_pref = profile.get("remote_preference", "any")
    if remote_pref not in ("any", None) and job.get("remote_type") and remote_pref != job["remote_type"]:
        score -= 40
    min_salary = profile.get("min_salary")
    job_salary_max = job.get("salary_max")
    if min_salary and job_salary_max and job_salary_max < min_salary:
        score -= 40
    return max(score, 0.0)


def _clean_recommendation(value) -> str:
    if isinstance(value, str) and value.strip().lower() in VALID_RECOMMENDATIONS:
        return value.strip().lower()
    return "consider"


def _resolve_model_env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value in DEPRECATED_MODELS:
        return default
    return value


def _estimate_candidate_experience(profile_json: dict) -> float:
    skills_exp = profile_json.get("years_experience_by_skill") or {}
    if isinstance(skills_exp, dict) and skills_exp:
        vals = [float(v) for v in skills_exp.values() if isinstance(v, (int, float))]
        if vals:
            return round(max(vals), 1)
    seniority = (profile_json.get("seniority") or "").lower()
    if seniority in ("junior", "entry"):
        return 1.5
    if seniority in ("mid", "semi-senior"):
        return 3.0
    if seniority in ("senior", "lead"):
        return 6.0
    return 3.0


def evaluate_job_with_llm(profile_json: dict, job: dict, profile_meta: dict | None = None) -> dict:
    model = _resolve_model_env("OPENROUTER_MODEL_SCORING", DEFAULT_SCORING_MODEL)
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")

    candidate_years = _estimate_candidate_experience(profile_json)
    candidate_seniority = profile_json.get("seniority") or "mid"
    excluded = (profile_meta and profile_meta.get("excluded_keywords")) or []
    excluded_summary = ", ".join(excluded) if excluded else "ninguna especificada"

    prompt = prompt_template.format(
        profile_json=profile_json,
        candidate_years=candidate_years,
        candidate_seniority=candidate_seniority,
        excluded_keywords_summary=excluded_summary,
        job_title=job.get("title", ""),
        job_company=job.get("company", ""),
        job_location=job.get("location", ""),
        job_remote_type=job.get("remote_type", ""),
        job_description=(job.get("description") or "")[:4000],
    )

    validated: JobEvaluationSchema = call_llm_structured(model, prompt, JobEvaluationSchema)

    return {
        "llm_score": validated.score,
        "salary": validated.salary,
        "pros": validated.pros,
        "cons": validated.cons,
        "missing_requirements": validated.missing_requirements,
        "recommendation": validated.recommendation,
    }


def compute_final_score(vector_similarity: float, hard_req_score: float, llm_score: int, recommendation: str = "consider") -> float:
    base = 0.4 * vector_similarity * 100 + 0.3 * hard_req_score + 0.3 * llm_score
    if recommendation == "skip":
        # Penalización severa para ofertas descartadas por requisitos excluyentes
        return round(min(base * 0.3, 20.0), 2)
    return round(base, 2)
