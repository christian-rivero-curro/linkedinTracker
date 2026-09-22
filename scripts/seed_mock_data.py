#!/usr/bin/env bash
# Seed script for realistic mock jobs in local database
"""
scripts/seed_mock_data.py
Inserta ofertas de empleo realistas, evaluaciones LLM y estados variados (Entrevista, Solicitada, Nueva, Vista, Descartada)
para el usuario 'christian' (y 'sabrina') para probar la interfaz visualmente.
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
load_dotenv()

from sqlalchemy import text
from app.db import get_engine

def seed_mock_jobs():
    engine = get_engine()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        # Obtener ID de christian
        user_row = conn.execute(text("SELECT id FROM app_user WHERE username = 'christian';")).fetchone()
        if not user_row:
            print("[!] Usuario 'christian' no encontrado. Ejecuta primero init_database.py.")
            return
        user_id = user_row[0]

        # Obtener variantes de christian
        variants = conn.execute(
            text("SELECT id, query_text FROM search_query_variant WHERE user_id = :uid;"),
            {"uid": user_id}
        ).fetchall()
        variant_map = {v[1].lower(): v[0] for v in variants}
        def_var_id = variants[0][0] if variants else None

        # Perfil de ejemplo para christian si no existe
        prof_exists = conn.execute(
            text("SELECT id FROM profile WHERE user_id = :uid;"),
            {"uid": user_id}
        ).fetchone()

        if not prof_exists:
            sample_profile = {
                "name": "Christian Rivero",
                "headline": "Senior Cloud & AI Solutions Architect",
                "summary": "Arquitecto Cloud con más de 10 años de experiencia diseñando plataformas escalables en AWS/GCP/Azure, microservicios Kubernetes y arquitecturas de IA generativa.",
                "skills": ["AWS", "GCP", "Kubernetes", "Terraform", "Python", "FastAPI", "Docker", "LLM", "RAG", "System Design"],
                "years_experience": 10
            }
            conn.execute(
                text("""
                    INSERT INTO profile (user_id, raw_cv_text, extracted_json, role_family, location_preference, remote_preference, min_salary, enabled_sources)
                    VALUES (:uid, :raw_cv, :json_data, :role_fam, 'Madrid, España', 'any', 60000, '{"linkedin","topsalaries","indeed","infojobs"}')
                    ON CONFLICT (user_id) DO NOTHING;
                """),
                {
                    "uid": user_id,
                    "raw_cv": sample_profile["summary"],
                    "json_data": json.dumps(sample_profile),
                    "role_fam": ["Cloud Architect", "AI Solutions Engineer", "AI Architect"],
                }
            )
            print("[+] Perfil de ejemplo creado para christian.")

        # Obtener profile_id de christian
        prof_row = conn.execute(
            text("SELECT id FROM profile WHERE user_id = :uid;"),
            {"uid": user_id}
        ).fetchone()
        profile_id = prof_row[0] if prof_row else None

        # Ofertas mock variadas
        mock_jobs = [
            {
                "external_id": "mock-dd-001",
                "title": "Senior Cloud Solutions Architect",
                "company": "Datadog",
                "location": "Madrid, España",
                "remote_type": "hybrid",
                "source": "linkedin",
                "is_easy_apply": True,
                "salary_raw": "75.000 € - 90.000 €",
                "salary_min": 75000,
                "salary_max": 90000,
                "apply_link": "https://www.datadoghq.com/careers/detail/?gh_jid=mock1",
                "variant_text": "cloud architect",
                "posted_days_ago": 2,
                "score": 91.5,
                "llm_score": 92,
                "status": "interview", # 📞 Entrevista
                "recommendation": "consider",
                "discard_reason": None,
                "pros": [
                    "Diseño de arquitectura distribuida multicloud para telemetría a gran escala.",
                    "Excelente rango salarial y paquete de equity (RSUs).",
                    "Stack tecnológico 100% alineado: AWS, Go, Python, Kubernetes, Terraform."
                ],
                "cons": [
                    "Requiere guardias rotativas de soporte de arquitectura de nivel 3."
                ],
                "missing": ["Experiencia previa directa con Datadog Agent internals (fácilmente subsanable)."]
            },
            {
                "external_id": "mock-snow-002",
                "title": "Lead AI Solutions Engineer",
                "company": "Snowflake",
                "location": "Barcelona, España",
                "remote_type": "remote",
                "source": "topsalaries",
                "salary_raw": "85.000 € - 105.000 €",
                "salary_min": 85000,
                "salary_max": 105000,
                "apply_link": "https://careers.snowflake.com/job/mock2",
                "variant_text": "ai solutions engineer",
                "posted_days_ago": 1,
                "score": 88.0,
                "llm_score": 87,
                "status": "applied", # ✓ Solicitada
                "recommendation": "consider",
                "discard_reason": None,
                "pros": [
                    "Puesto 100% remoto con gran autonomía y proyección internacional.",
                    "Fuerte enfoque en despliegue de modelos LLM sobre Snowflake Cortex y vector search.",
                    "Rango salarial superior a mercado."
                ],
                "cons": [
                    "Coordinación horaria puntual con equipos de San Mateo (PST)."
                ],
                "missing": ["Certificación Snowflake SnowPro Advanced Architect."]
            },
            {
                "external_id": "mock-aws-003",
                "title": "Principal Cloud Architect - Generative AI",
                "company": "Amazon Web Services (AWS)",
                "location": "Madrid, España",
                "remote_type": "hybrid",
                "source": "linkedin",
                "salary_raw": "95.000 € - 120.000 €",
                "salary_min": 95000,
                "salary_max": 120000,
                "apply_link": "https://amazon.jobs/en/jobs/mock3",
                "variant_text": "ai architect",
                "posted_days_ago": 4,
                "score": 94.5,
                "llm_score": 95,
                "status": "interview", # 📞 Entrevista
                "recommendation": "consider",
                "discard_reason": None,
                "pros": [
                    "Rol de máximo impacto estratégico asesorando a clientes Tier 1 en Europa.",
                    "Liderazgo en adopción de Bedrock, SageMaker y arquitecturas RAG empresariales.",
                    "Paquete retributivo excepcional con bonus anual y acciones."
                ],
                "cons": [
                    "Viajes ocasionales a clientes en la región EMEA (aprox. 15-20%)."
                ],
                "missing": ["Deseable publicación o autoría en conferencias técnicas cloud."]
            },
            {
                "external_id": "mock-cabi-004",
                "title": "Staff Cloud Platform Architect",
                "company": "Cabify",
                "location": "Madrid, España",
                "remote_type": "remote",
                "source": "infojobs",
                "salary_raw": "68.000 € - 82.000 €",
                "salary_min": 68000,
                "salary_max": 82000,
                "apply_link": "https://cabify.careers/mock4",
                "variant_text": "cloud architect",
                "posted_days_ago": 3,
                "score": 84.0,
                "llm_score": 83,
                "status": "new", # Nueva
                "recommendation": "consider",
                "discard_reason": None,
                "pros": [
                    "Cultura tecnológica reconocida, ingeniería moderna y trabajo 100% remoto en España.",
                    "Gestión de plataforma core sobre Google Cloud Platform y clusters GKE masivos."
                ],
                "cons": [
                    "Salario algo inferior respecto a multinacionales americanas."
                ],
                "missing": ["Experiencia específica en Elixir/Go para tooling interno de plataforma."]
            },
            {
                "external_id": "mock-type-005",
                "title": "Senior AI Infrastructure Engineer",
                "company": "Typeform",
                "location": "Barcelona, España",
                "remote_type": "remote",
                "source": "indeed",
                "salary_raw": "65.000 € - 78.000 €",
                "salary_min": 65000,
                "salary_max": 78000,
                "apply_link": "https://www.typeform.com/careers/mock5",
                "variant_text": "ai engineer",
                "posted_days_ago": 5,
                "score": 81.0,
                "llm_score": 80,
                "status": "viewed", # Vista
                "recommendation": "consider",
                "discard_reason": None,
                "pros": [
                    "Empresa de producto SaaS con foco intensivo en IA conversational y workflows guiados.",
                    "Stack moderno en AWS EKS, vLLM y pipelines de embeddings en tiempo real."
                ],
                "cons": [
                    "Equipo de reciente creación con metodologías en proceso de maduración."
                ],
                "missing": ["Conocimientos avanzados en optimización de pesos cuantizados (AWQ/GPTQ)."]
            },
            {
                "external_id": "mock-sant-006",
                "title": "Cloud Architect - Core Banking Modernization",
                "company": "Banco Santander",
                "location": "Boadilla del Monte, Madrid",
                "remote_type": "hybrid",
                "source": "linkedin",
                "salary_raw": "60.000 € - 72.000 €",
                "salary_min": 60000,
                "salary_max": 72000,
                "apply_link": "https://santander.com/careers/mock6",
                "variant_text": "cloud architect",
                "posted_days_ago": 6,
                "score": 73.0,
                "llm_score": 72,
                "status": "applied", # ✓ Solicitada
                "recommendation": "consider",
                "discard_reason": None,
                "pros": [
                    "Estabilidad financiera y gran escala de operaciones.",
                    "Migración de mainframe hacia plataforma Gravity Cloud."
                ],
                "cons": [
                    "Entorno corporativo financiero con burocracia de cumplimiento normativo (DORA/EBA)."
                ],
                "missing": ["Certificación en normativas de banca europea."]
            },
            {
                "external_id": "mock-sc-007",
                "title": "DevOps & Cloud Systems Architect",
                "company": "Scalable Capital",
                "location": "Madrid, España",
                "remote_type": "remote",
                "source": "topsalaries",
                "salary_raw": "58.000 € - 70.000 €",
                "salary_min": 58000,
                "salary_max": 70000,
                "apply_link": "https://scalable.capital/careers/mock7",
                "variant_text": "cloud architect",
                "posted_days_ago": 7,
                "score": 67.5,
                "llm_score": 65,
                "status": "new", # Nueva
                "recommendation": "consider",
                "discard_reason": None,
                "pros": [
                    "Fintech de alto crecimiento con tecnología puntera en Alemania y España.",
                    "Presupuesto de formación anual y eventos internacionales."
                ],
                "cons": [
                    "Horarios muy ajustados al mercado bursátil europeo."
                ],
                "missing": ["Experiencia en fintech regulada BaFin."]
            },
            {
                "external_id": "mock-help-008",
                "title": "Técnico de Soporte Helpdesk L1 / Microinformática",
                "company": "TechSolutions Madrid SL",
                "location": "Madrid, España",
                "remote_type": "onsite",
                "source": "infojobs",
                "salary_raw": "21.000 € - 24.000 €",
                "salary_min": 21000,
                "salary_max": 24000,
                "apply_link": "https://infojobs.net/mock8",
                "variant_text": "cloud architect",
                "posted_days_ago": 8,
                "score": 31.0,
                "llm_score": 25,
                "status": "discarded", # Descartada
                "recommendation": "skip", # No cumple requisitos
                "discard_reason": "Posición de soporte técnico básico presencial; no coincide con perfil Senior Cloud/AI Architect.",
                "pros": [
                    "Ubicación céntrica en Madrid."
                ],
                "cons": [
                    "Salario no acorde con perfil senior.",
                    "Tareas de cableado, impresoras y soporte presencial a usuarios.",
                    "100% presencial sin componentes de arquitectura cloud."
                ],
                "missing": ["Puesto completamente no aplicable."]
            }
        ]

        count = 0
        for job in mock_jobs:
            var_id = variant_map.get(job["variant_text"].lower(), def_var_id)
            posted_date = now - timedelta(days=job["posted_days_ago"], hours=4)
            fetched_date = now - timedelta(days=job["posted_days_ago"], hours=1)

            # Insertar o actualizar job_offer
            jo_id = conn.execute(
                text("""
                    INSERT INTO job_offer (user_id, external_id, title, company, location, remote_type, description, apply_link, source, salary_raw, salary_min, salary_max, posted_at, fetched_at, variant_id, is_easy_apply)
                    VALUES (:uid, :ext_id, :title, :company, :location, :remote, :desc, :link, :src, :sal_raw, :sal_min, :sal_max, :posted, :fetched, :var_id, :is_easy)
                    ON CONFLICT (user_id, external_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        company = EXCLUDED.company,
                        location = EXCLUDED.location,
                        remote_type = EXCLUDED.remote_type,
                        salary_raw = EXCLUDED.salary_raw,
                        apply_link = EXCLUDED.apply_link,
                        variant_id = EXCLUDED.variant_id,
                        is_easy_apply = EXCLUDED.is_easy_apply
                    RETURNING id;
                """),
                {
                    "uid": user_id,
                    "ext_id": job["external_id"],
                    "title": job["title"],
                    "company": job["company"],
                    "location": job["location"],
                    "remote": job["remote_type"],
                    "desc": f"Descripción de la posición {job['title']} en {job['company']}.\nBuscamos profesionales apasionados para liderar proyectos innovadores...",
                    "link": job["apply_link"],
                    "src": job["source"],
                    "sal_raw": job["salary_raw"],
                    "sal_min": job["salary_min"],
                    "sal_max": job["salary_max"],
                    "posted": posted_date,
                    "fetched": fetched_date,
                    "var_id": var_id,
                    "is_easy": bool(job.get("is_easy_apply", False))
                }
            ).fetchone()[0]

            # Insertar o actualizar job_score
            conn.execute(
                text("""
                    INSERT INTO job_score (user_id, profile_id, job_offer_id, final_score, llm_score, vector_similarity, pros, cons, missing_requirements, recommendation, status, discard_reason, llm_evaluated)
                    VALUES (:uid, :prof_id, :j_id, :score, :llm_s, 0.85, :pros, :cons, :miss_e, :rec, :status, :disc_r, TRUE)
                    ON CONFLICT (job_offer_id, profile_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        final_score = EXCLUDED.final_score,
                        llm_score = EXCLUDED.llm_score,
                        recommendation = EXCLUDED.recommendation,
                        status = EXCLUDED.status,
                        discard_reason = EXCLUDED.discard_reason,
                        pros = EXCLUDED.pros,
                        cons = EXCLUDED.cons,
                        missing_requirements = EXCLUDED.missing_requirements,
                        llm_evaluated = TRUE;
                """),
                {
                    "uid": user_id,
                    "prof_id": profile_id,
                    "j_id": jo_id,
                    "score": job["score"],
                    "llm_s": job["llm_score"],
                    "pros": job["pros"],
                    "cons": job["cons"],
                    "miss_e": job["missing"],
                    "rec": job["recommendation"],
                    "status": job["status"],
                    "disc_r": job["discard_reason"],
                }
            )
            count += 1



        print(f"[+] Se han insertado/actualizado con éxito {count} ofertas de prueba con estados variados para christian.")

if __name__ == "__main__":
    seed_mock_jobs()
