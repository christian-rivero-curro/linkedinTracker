"""
Similitud vectorial + orquestacion de la evaluacion cualitativa por LLM.
"""
import os
from pathlib import Path

from pipeline.llm_client import call_llm_json
from pipeline.embeddings import cosine_similarity

PROMPT_PATH = Path(__file__).parent / "prompts" / "evaluate_job.txt"

BLACKLIST_KEYWORDS = [
    "marketing", "sales", "ventas", "legal", "teacher", "docente",
    "recruiter", "reclutador", "comercial", "abogado",
]


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


def evaluate_job_with_llm(profile_json: dict, job: dict) -> dict:
    model = os.environ.get("OPENROUTER_MODEL_SCORING", "minimax/minimax-m2.7:free")
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        profile_json=profile_json,
        job_title=job.get("title", ""),
        job_company=job.get("company", ""),
        job_location=job.get("location", ""),
        job_remote_type=job.get("remote_type", ""),
        job_description=(job.get("description") or "")[:4000],
    )
    result = call_llm_json(model, prompt)
    return {
        "llm_score": int(result.get("score", 0)),
        "pros": result.get("pros", []),
        "cons": result.get("cons", []),
        "missing_requirements": result.get("missing_requirements", []),
        "recommendation": result.get("recommendation", "consider"),
    }


def compute_final_score(vector_similarity: float, hard_req_score: float, llm_score: int) -> float:
    return round(0.4 * vector_similarity * 100 + 0.3 * hard_req_score + 0.3 * llm_score, 2)
