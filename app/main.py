import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from dotenv import load_dotenv

from app.db import get_engine
from app.schemas import JobStatusUpdate
from app.auth import (
    get_current_user,
    get_current_user_optional,
    can_register_user,
    hash_password,
    verify_password,
    create_session_token,
    SESSION_COOKIE_NAME,
    get_max_users,
)
from pipeline.cv_extractor import extract_cv
from pipeline.embeddings import to_pgvector_literal
from pipeline.query_variants import get_all_variants, generate_variants_via_llm, add_ai_variants, seed_default_variants

load_dotenv()

app = FastAPI(title="linkedinTracker")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.on_event("startup")
def startup_db_migrations():
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE profile ALTER COLUMN embedding DROP NOT NULL;"))
    except Exception as e:
        print(f"[startup] Info restriccion embedding: {e}")


# ---------------------------------------------------------------------------
# RUTAS DE AUTENTICACIÓN
# ---------------------------------------------------------------------------

@app.get("/login")
def login_form(request: Request, next: str = ""):
    user = get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "current_user": None, "next": next, "error": None, "message": None},
    )


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("")):
    clean_user = username.strip()
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, username, password_hash, is_active FROM app_user WHERE lower(username) = lower(:u)"),
            {"u": clean_user},
        ).mappings().first()

    if not row or not verify_password(password, row["password_hash"]):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "current_user": None, "next": next, "error": "Usuario o contraseña incorrectos.", "message": None},
            status_code=400,
        )

    if not row["is_active"]:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "current_user": None, "next": next, "error": "Esta cuenta de usuario está desactivada.", "message": None},
            status_code=403,
        )

    token = create_session_token(row["id"], row["username"])
    redirect_url = next if (next and next.startswith("/")) else "/dashboard"
    resp = RedirectResponse(url=redirect_url, status_code=303)
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 14,
    )
    return resp


@app.get("/register")
def register_form(request: Request):
    user = get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)

    engine = get_engine()
    can_reg, cur_count, max_u = can_register_user(engine)
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "current_user": None,
            "can_register": can_reg,
            "current_count": cur_count,
            "max_users": max_u,
            "error": None,
        },
    )


@app.post("/register")
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    engine = get_engine()
    can_reg, cur_count, max_u = can_register_user(engine)
    if not can_reg:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "current_user": None,
                "can_register": False,
                "current_count": cur_count,
                "max_users": max_u,
                "error": f"Límite máximo de usuarios alcanzado ({cur_count}/{max_u}).",
            },
            status_code=400,
        )

    clean_user = username.strip()
    if len(clean_user) < 3:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "current_user": None,
                "can_register": True,
                "current_count": cur_count,
                "max_users": max_u,
                "error": "El nombre de usuario debe tener al menos 3 caracteres.",
            },
            status_code=400,
        )

    if len(password) < 4:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "current_user": None,
                "can_register": True,
                "current_count": cur_count,
                "max_users": max_u,
                "error": "La contraseña debe tener al menos 4 caracteres.",
            },
            status_code=400,
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "current_user": None,
                "can_register": True,
                "current_count": cur_count,
                "max_users": max_u,
                "error": "Las contraseñas no coinciden.",
            },
            status_code=400,
        )

    # Verificar si el usuario ya existe
    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT id FROM app_user WHERE lower(username) = lower(:u)"),
            {"u": clean_user},
        ).first()

    if existing:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "current_user": None,
                "can_register": True,
                "current_count": cur_count,
                "max_users": max_u,
                "error": f"El nombre de usuario '{clean_user}' ya está registrado.",
            },
            status_code=400,
        )

    pwd_hash = hash_password(password)
    with engine.begin() as conn:
        new_user_id = conn.execute(
            text("INSERT INTO app_user (username, password_hash) VALUES (:u, :p) RETURNING id"),
            {"u": clean_user, "p": pwd_hash},
        ).scalar()

    token = create_session_token(new_user_id, clean_user)
    resp = RedirectResponse(url="/onboarding", status_code=303)
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 14,
    )
    return resp


@app.post("/logout")
@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(key=SESSION_COOKIE_NAME)
    return resp


# ---------------------------------------------------------------------------
# RUTAS PROTEGIDAS
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/onboarding")
def onboarding_form(request: Request, current_user: dict = Depends(get_current_user)):
    engine = get_engine()
    user_id = current_user["id"]
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT raw_cv_text, location_preference, remote_preference, role_family, min_salary
                FROM profile WHERE user_id = :uid
            """),
            {"uid": user_id},
        ).mappings().first()
    profile = dict(row) if row else None

    try:
        variants = get_all_variants(engine, user_id=user_id)
    except Exception as e:
        print(f"[onboarding] Error leyendo variantes del usuario {user_id}: {e}")
        variants = []

    clean_variants = [
        {
            "id": v.get("id"),
            "query_text": v.get("query_text", ""),
            "source": v.get("source", "manual"),
            "is_active": bool(v.get("is_active", True)),
        }
        for v in variants
    ]

    return templates.TemplateResponse(
        "onboarding.html",
        {
            "request": request,
            "current_user": current_user,
            "has_profile": profile is not None,
            "profile": profile,
            "variants": clean_variants,
        },
    )


@app.post("/onboarding")
def onboarding_submit(
    request: Request,
    raw_cv_text: str = Form(...),
    location_preference: str = Form(""),
    remote_preference: str = Form("any"),
    role_family: str = Form(""),
    min_salary: str = Form(""),
    variants_json: str = Form("[]"),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    try:
        extracted = extract_cv(raw_cv_text)
    except Exception as e:
        print(f"[onboarding] Error en extraccion de CV con LLM: {e}")
        roles_list = [r.strip() for r in role_family.split(",") if r.strip()]
        extracted = {
            "skills": roles_list,
            "years_experience_by_skill": {},
            "seniority": "mid",
            "equivalent_roles": roles_list,
            "languages": [],
            "certifications": [],
        }
    # Placeholder inicial rápido y ligero: vector de ceros que satisface restricciones
    # NOT NULL sin importar librerías pesadas en el servidor web.
    # El pipeline en GitHub Actions (7GB RAM) calculará el embedding semántico real.
    placeholder_emb = [0.0] * 384

    roles = [r.strip() for r in role_family.split(",") if r.strip()]
    salary = int(min_salary) if min_salary.strip().isdigit() else None

    engine = get_engine()
    with engine.begin() as conn:
        profile_id = conn.execute(
            text("""
                INSERT INTO profile (user_id, raw_cv_text, extracted_json, embedding, location_preference,
                    remote_preference, role_family, min_salary)
                VALUES (:user_id, :raw_cv_text, CAST(:extracted_json AS jsonb), CAST(:embedding AS vector), :location_preference,
                    :remote_preference, :role_family, :min_salary)
                ON CONFLICT (user_id) DO UPDATE SET
                    raw_cv_text = EXCLUDED.raw_cv_text,
                    extracted_json = EXCLUDED.extracted_json,
                    embedding = COALESCE(profile.embedding, EXCLUDED.embedding),
                    location_preference = EXCLUDED.location_preference,
                    remote_preference = EXCLUDED.remote_preference,
                    role_family = EXCLUDED.role_family,
                    min_salary = EXCLUDED.min_salary,
                    updated_at = now()
                RETURNING id
            """),
            {
                "user_id": user_id,
                "raw_cv_text": raw_cv_text,
                "extracted_json": json.dumps(extracted),
                "embedding": to_pgvector_literal(placeholder_emb),
                "location_preference": location_preference or None,
                "remote_preference": remote_preference,
                "role_family": roles,
                "min_salary": salary,
            },
        ).scalar()

        # Sincronizar variantes si se envió variants_json
        submitted_variants = None
        if variants_json:
            try:
                submitted_variants = json.loads(variants_json)
            except Exception as json_err:
                print(f"[onboarding] Error parseando variants_json: {json_err}")

        if isinstance(submitted_variants, list):
            existing_rows = conn.execute(
                text("SELECT id FROM search_query_variant WHERE user_id = :uid"),
                {"uid": user_id},
            ).fetchall()
            existing_ids = {r[0] for r in existing_rows}

            submitted_ids = {v["id"] for v in submitted_variants if v.get("id")}
            to_delete = existing_ids - submitted_ids
            if to_delete:
                conn.execute(
                    text("DELETE FROM search_query_variant WHERE id = ANY(:ids) AND user_id = :uid"),
                    {"ids": list(to_delete), "uid": user_id},
                )

            for idx, item in enumerate(submitted_variants):
                q_text = (item.get("query_text") or "").strip()
                if not q_text:
                    continue
                is_active = bool(item.get("is_active", True))
                source = item.get("source") or "manual"
                if source not in ("ai", "manual"):
                    source = "manual"
                item_id = item.get("id")

                if item_id and item_id in existing_ids:
                    conn.execute(
                        text("""
                            UPDATE search_query_variant
                            SET query_text = :qt, is_active = :act, order_index = :idx, profile_id = :pid, updated_at = now()
                            WHERE id = :id AND user_id = :uid
                        """),
                        {"qt": q_text, "act": is_active, "idx": idx, "pid": profile_id, "id": item_id, "uid": user_id},
                    )
                else:
                    conn.execute(
                        text("""
                            INSERT INTO search_query_variant (profile_id, user_id, query_text, source, is_active, order_index)
                            VALUES (:pid, :uid, :qt, :src, :act, :idx)
                        """),
                        {"pid": profile_id, "uid": user_id, "qt": q_text, "src": source, "act": is_active, "idx": idx},
                    )

    # Sembrar variantes iniciales si no tiene ninguna tras guardar
    with engine.connect() as conn:
        var_count = conn.execute(
            text("SELECT COUNT(*) FROM search_query_variant WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar()

    if not var_count:
        profile_dict = {
            "id": profile_id,
            "user_id": user_id,
            "extracted_json": extracted,
            "role_family": roles,
        }
        seed_default_variants(engine, profile_id, profile_dict)

    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/api/onboarding/suggest-variants")
async def suggest_variants_api(request: Request, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    try:
        body = await request.json()
    except Exception:
        body = {}

    cv_text = (body.get("raw_cv_text") or "").strip()
    role_family = (body.get("role_family") or "").strip()
    roles = [r.strip() for r in role_family.split(",") if r.strip()]

    if not cv_text and not roles:
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT raw_cv_text, role_family, extracted_json FROM profile WHERE user_id = :uid"),
                {"uid": user_id},
            ).mappings().first()
            if row:
                cv_text = row["raw_cv_text"] or ""
                if not roles:
                    roles = row["role_family"] or []

    if not cv_text and not roles:
        return JSONResponse(
            status_code=400,
            content={"error": "Escribe o pega primero el texto de tu CV o indica familias de rol."},
        )

    profile_mock = {
        "extracted_json": {"skills": roles, "equivalent_roles": roles, "seniority": "mid"},
        "role_family": roles,
        "raw_cv_text": cv_text,
    }

    try:
        suggestions = generate_variants_via_llm(profile_mock)
        return {"variants": suggestions}
    except Exception as e:
        print(f"[suggest-variants] Error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Error al generar sugerencias: {e}"})



@app.post("/onboarding/variants/add")
def add_variant(query_text: str = Form(...), current_user: dict = Depends(get_current_user)):
    cleaned = query_text.strip()
    user_id = current_user["id"]
    if cleaned:
        engine = get_engine()
        with engine.connect() as conn:
            p_id = conn.execute(text("SELECT id FROM profile WHERE user_id = :uid"), {"uid": user_id}).scalar()
            max_order = conn.execute(
                text("SELECT COALESCE(MAX(order_index), -1) FROM search_query_variant WHERE user_id = :uid"),
                {"uid": user_id},
            ).scalar()
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO search_query_variant (profile_id, user_id, query_text, source, order_index)
                    VALUES (:pid, :uid, :qt, 'manual', :order_index)
                """),
                {"pid": p_id, "uid": user_id, "qt": cleaned, "order_index": max_order + 1},
            )
    return RedirectResponse(url="/onboarding", status_code=303)


@app.post("/onboarding/variants/{variant_id}/update")
def update_variant(variant_id: int, query_text: str = Form(...), current_user: dict = Depends(get_current_user)):
    cleaned = query_text.strip()
    user_id = current_user["id"]
    if cleaned:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE search_query_variant SET query_text = :qt, updated_at = now()
                    WHERE id = :id AND user_id = :uid
                """),
                {"qt": cleaned, "id": variant_id, "uid": user_id},
            )
    return RedirectResponse(url="/onboarding", status_code=303)


@app.post("/onboarding/variants/{variant_id}/toggle")
def toggle_variant(variant_id: int, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE search_query_variant SET is_active = NOT is_active, updated_at = now()
                WHERE id = :id AND user_id = :uid
            """),
            {"id": variant_id, "uid": user_id},
        )
    return RedirectResponse(url="/onboarding", status_code=303)


@app.post("/onboarding/variants/{variant_id}/delete")
def delete_variant(variant_id: int, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM search_query_variant WHERE id = :id AND user_id = :uid"),
            {"id": variant_id, "uid": user_id},
        )
    return RedirectResponse(url="/onboarding", status_code=303)


@app.post("/onboarding/variants/generate")
def generate_variants(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM profile WHERE user_id = :uid"), {"uid": user_id}).mappings().first()
    if row is not None:
        profile = dict(row)
        try:
            suggestions = generate_variants_via_llm(profile)
            add_ai_variants(engine, profile["id"], suggestions, user_id=user_id)
        except Exception as e:
            print(f"[onboarding] Error generando variantes con IA para user {user_id}: {e}")
    return RedirectResponse(url="/onboarding", status_code=303)


def _parse_bool_param(value: str) -> bool:
    return value.strip().lower() not in ("", "0", "false", "no")


@app.get("/dashboard")
def dashboard(
    request: Request,
    status: str = "all",
    show_skipped: str = "",
    show_discarded: str = "",
    variant_id: str = "all",
    current_user: dict = Depends(get_current_user),
):
    show_skipped_bool = _parse_bool_param(show_skipped)
    show_discarded_bool = _parse_bool_param(show_discarded)
    user_id = current_user["id"]
    engine = get_engine()

    query = """
        SELECT js.id, jo.title, jo.company, jo.location, jo.remote_type, jo.apply_link,
               jo.source, jo.posted_at, jo.fetched_at, jo.variant_id, sqv.query_text AS variant_query,
               js.final_score, js.llm_score, js.status, js.llm_evaluated, js.recommendation, js.discard_reason,
               jo.salary_raw
        FROM job_score js
        JOIN job_offer jo ON jo.id = js.job_offer_id
        LEFT JOIN search_query_variant sqv ON sqv.id = jo.variant_id
        WHERE js.user_id = :user_id AND js.llm_evaluated = TRUE
    """
    params = {"user_id": user_id}
    if not show_skipped_bool:
        query += " AND COALESCE(js.recommendation, 'consider') != 'skip'"
    if status != "all":
        query += " AND js.status = :status"
        params["status"] = status
    elif not show_discarded_bool:
        query += " AND js.status != 'discarded'"
    if variant_id != "all" and variant_id.strip().isdigit():
        query += " AND jo.variant_id = :variant_id"
        params["variant_id"] = int(variant_id)
    query += " ORDER BY js.final_score DESC LIMIT 100"

    with engine.connect() as conn:
        rows = conn.execute(text(query), params).mappings().all()
        pending_llm_count = conn.execute(
            text("SELECT COUNT(*) FROM job_score WHERE user_id = :uid AND llm_evaluated = FALSE"),
            {"uid": user_id},
        ).scalar()

    try:
        variants = get_all_variants(engine, user_id=user_id)
    except Exception as e:
        print(f"[dashboard] No se pudieron leer las variantes para user {user_id}: {e}")
        variants = []

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "jobs": rows,
            "status": status,
            "show_skipped": show_skipped_bool,
            "show_discarded": show_discarded_bool,
            "variant_id": variant_id,
            "variants": variants,
            "pending_llm_count": pending_llm_count,
        },
    )


@app.get("/dashboard/{job_score_id}")
def dashboard_detail(request: Request, job_score_id: int, current_user: dict = Depends(get_current_user)):
    engine = get_engine()
    user_id = current_user["id"]
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT js.*, jo.title, jo.company, jo.location, jo.remote_type,
                       jo.description, jo.apply_link, jo.source, jo.posted_at, jo.fetched_at,
                       jo.variant_id, sqv.query_text AS variant_query, jo.salary_raw
                FROM job_score js
                JOIN job_offer jo ON jo.id = js.job_offer_id
                LEFT JOIN search_query_variant sqv ON sqv.id = jo.variant_id
                WHERE js.id = :id AND js.user_id = :uid
            """),
            {"id": job_score_id, "uid": user_id},
        ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Oferta no encontrada o no pertenece a tu usuario.")

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "current_user": current_user, "detail": row, "jobs": []},
    )


@app.post("/dashboard/clear-jobs")
def clear_jobs(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM job_offer WHERE user_id = :uid"), {"uid": user_id})
        conn.execute(
            text("UPDATE search_query_variant SET last_posted_cutoff_utc = NULL, last_run_at = NULL WHERE user_id = :uid"),
            {"uid": user_id},
        )
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/api/job/{job_score_id}/status")
def update_job_status(job_score_id: int, payload: JobStatusUpdate, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    discard_reason = payload.reason.strip() if (payload.status == "discarded" and payload.reason) else None
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE job_score SET status = :status, discard_reason = :discard_reason WHERE id = :id AND user_id = :uid"),
            {"status": payload.status, "discard_reason": discard_reason, "id": job_score_id, "uid": user_id},
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Oferta no encontrada.")
# ---------------------------------------------------------------------------
# BÚSQUEDA BAJO DEMANDA POR USUARIO (BACKGROUND TASK)
# ---------------------------------------------------------------------------

_discovery_tasks: dict[int, dict] = {}


def _run_user_discovery_background(user_id: int, username: str):
    _discovery_tasks[user_id] = {
        "status": "running",
        "stage": "linkedin_scrape",
        "message": f"Buscando vacantes en LinkedIn para {username}...",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "new_jobs_found": 0,
        "evaluated_count": 0,
        "error": None,
    }
    try:
        from pipeline.run_linkedin_guest import main as run_linkedin
        from pipeline.run_llm_evaluation import main as run_llm

        # 1. Scraping de LinkedIn para este usuario
        linkedin_res = run_linkedin(target_user_id=user_id)
        new_jobs = (linkedin_res or {}).get("new_jobs_found", 0)
        _discovery_tasks[user_id]["new_jobs_found"] = new_jobs

        # 2. Evaluación con LLM para las ofertas pendientes de este usuario
        _discovery_tasks[user_id]["stage"] = "llm_evaluation"
        _discovery_tasks[user_id]["message"] = f"Evaluando con LLM las vacantes de {username}..."

        llm_res = run_llm(target_user_id=user_id)
        eval_count = (llm_res or {}).get("evaluated_count", 0)
        _discovery_tasks[user_id]["evaluated_count"] = eval_count

        _discovery_tasks[user_id]["status"] = "completed"
        _discovery_tasks[user_id]["stage"] = "done"
        _discovery_tasks[user_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
        _discovery_tasks[user_id]["message"] = (
            f"Proceso finalizado: {new_jobs} nueva{'s' if new_jobs != 1 else ''} vacante{'s' if new_jobs != 1 else ''} "
            f"y {eval_count} evaluada{'s' if eval_count != 1 else ''} con éxito."
        )
    except Exception as e:
        _discovery_tasks[user_id]["status"] = "error"
        _discovery_tasks[user_id]["error"] = str(e)
        _discovery_tasks[user_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
        _discovery_tasks[user_id]["message"] = f"Error durante la búsqueda: {e}"


@app.post("/api/jobs/trigger-discovery")
def trigger_user_discovery(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    username = current_user["username"]

    current_task = _discovery_tasks.get(user_id)
    if current_task and current_task.get("status") == "running":
        return JSONResponse(
            status_code=409,
            content={
                "status": "running",
                "message": "Ya hay una búsqueda en curso para tu perfil.",
                "stage": current_task.get("stage"),
            },
        )

    _discovery_tasks[user_id] = {
        "status": "running",
        "stage": "starting",
        "message": "Iniciando búsqueda de ofertas...",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "new_jobs_found": 0,
        "evaluated_count": 0,
        "error": None,
    }
    background_tasks.add_task(_run_user_discovery_background, user_id, username)
    return {"status": "started", "message": f"Búsqueda iniciada para {username}."}


@app.get("/api/jobs/discovery-status")
def get_user_discovery_status(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    task_info = _discovery_tasks.get(user_id)
    if not task_info:
        return {"status": "idle", "message": "No hay búsquedas recientes."}
    return task_info


@app.post("/api/jobs/discovery-ack")
def acknowledge_user_discovery(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    task_info = _discovery_tasks.get(user_id)
    if task_info and task_info.get("status") in ("completed", "error"):
        _discovery_tasks[user_id] = {"status": "idle", "message": "Listo."}
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 7999))
    print(f"\n🌐 Dashboard disponible en: http://localhost:{port}/dashboard\n")
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
