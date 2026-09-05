import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from dotenv import load_dotenv

from app.db import get_engine
from app.schemas import JobStatusUpdate
from pipeline.cv_extractor import extract_cv
from pipeline.embeddings import embed_text, to_pgvector_literal

load_dotenv()

app = FastAPI(title="linkedinTracker")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/")
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/onboarding")
def onboarding_form(request: Request):
    engine = get_engine()
    with engine.connect() as conn:
        existing = conn.execute(text("SELECT id FROM profile WHERE id = 1")).first()
    return templates.TemplateResponse(
        "onboarding.html", {"request": request, "has_profile": existing is not None}
    )


@app.post("/onboarding")
def onboarding_submit(
    request: Request,
    raw_cv_text: str = Form(...),
    location_preference: str = Form(""),
    remote_preference: str = Form("any"),
    role_family: str = Form(""),
    min_salary: str = Form(""),
):
    extracted = extract_cv(raw_cv_text)
    embedding = embed_text(raw_cv_text)
    roles = [r.strip() for r in role_family.split(",") if r.strip()]
    salary = int(min_salary) if min_salary.strip().isdigit() else None

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO profile (id, raw_cv_text, extracted_json, embedding, location_preference,
                    remote_preference, role_family, min_salary)
                VALUES (1, :raw_cv_text, CAST(:extracted_json AS jsonb), CAST(:embedding AS vector), :location_preference,
                    :remote_preference, :role_family, :min_salary)
                ON CONFLICT (id) DO UPDATE SET
                    raw_cv_text = EXCLUDED.raw_cv_text,
                    extracted_json = EXCLUDED.extracted_json,
                    embedding = EXCLUDED.embedding,
                    location_preference = EXCLUDED.location_preference,
                    remote_preference = EXCLUDED.remote_preference,
                    role_family = EXCLUDED.role_family,
                    min_salary = EXCLUDED.min_salary,
                    updated_at = now()
            """),
            {
                "raw_cv_text": raw_cv_text,
                "extracted_json": json.dumps(extracted),
                "embedding": to_pgvector_literal(embedding),
                "location_preference": location_preference or None,
                "remote_preference": remote_preference,
                "role_family": roles,
                "min_salary": salary,
            },
        )
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/dashboard")
def dashboard(request: Request, status: str = "all"):
    engine = get_engine()
    query = """
        SELECT js.id, jo.title, jo.company, jo.location, jo.remote_type, jo.apply_link,
               jo.source, js.final_score, js.llm_score, js.status, js.llm_evaluated
        FROM job_score js
        JOIN job_offer jo ON jo.id = js.job_offer_id
        WHERE js.profile_id = 1
    """
    params = {}
    if status != "all":
        query += " AND js.status = :status"
        params["status"] = status
    query += " ORDER BY js.final_score DESC LIMIT 100"

    with engine.connect() as conn:
        rows = conn.execute(text(query), params).mappings().all()
    return templates.TemplateResponse("dashboard.html", {"request": request, "jobs": rows, "status": status})


@app.get("/dashboard/{job_score_id}")
def dashboard_detail(request: Request, job_score_id: int):
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT js.*, jo.title, jo.company, jo.location, jo.remote_type,
                       jo.description, jo.apply_link, jo.source
                FROM job_score js
                JOIN job_offer jo ON jo.id = js.job_offer_id
                WHERE js.id = :id
            """),
            {"id": job_score_id},
        ).mappings().first()
    return templates.TemplateResponse("dashboard.html", {"request": request, "detail": row, "jobs": []})


@app.post("/api/job/{job_score_id}/status")
def update_job_status(job_score_id: int, payload: JobStatusUpdate):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE job_score SET status = :status WHERE id = :id"),
            {"status": payload.status, "id": job_score_id},
        )
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
