"""
Entrypoint del scraper de LinkedIn. Pensado para ejecutarse EN LOCAL o en un
contenedor Docker en TU PROPIA maquina - NUNCA en GitHub Actions.

Requiere haber ejecutado antes pipeline/linkedin_login.py una vez para generar
la sesion guardada (ver LINKEDIN_STORAGE_STATE).

Cada variante usa una PESTANA NUEVA (context.new_page()), con listeners de
diagnostico enganchados (attach_diagnostics_listeners) para capturar errores
de consola JS, peticiones de red fallidas y respuestas 401/403 de la API
interna de LinkedIn - la causa mas probable de que la app se quede colgada en
su pantalla de carga sin llegar a mostrar resultados ni redirigir a login.

Reutiliza pipeline/job_ingest.py (verbose=True, para ver el motivo exacto de
cada oferta descartada) - mismo pipeline de scoring vectorial + evaluacion LLM
que run_discovery.py.

Fail-soft con una excepcion deliberada: si LinkedIn devuelve un
checkpoint/bloqueo, el script para INMEDIATAMENTE sin reintentar.
"""
import os
import sys
import random
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_engine  # noqa: E402
from pipeline.embeddings import parse_pgvector  # noqa: E402
from pipeline.job_ingest import process_and_store_job  # noqa: E402
from pipeline.query_variants import get_all_variants  # noqa: E402
from pipeline.linkedin_scraper import scrape_variant, new_browser_context, attach_diagnostics_listeners, LinkedInBlockedError  # noqa: E402


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        print(f"[run_linkedin_scrape] Valor invalido para {name}='{raw}', usando default {default}.")
        return default


LINKEDIN_HOURS_AGO = max(1, _int_env("LINKEDIN_HOURS_AGO", 4))
LINKEDIN_MAX_JOBS_PER_VARIANT = max(1, _int_env("LINKEDIN_MAX_JOBS_PER_VARIANT", 25))
LINKEDIN_HEADLESS = os.environ.get("LINKEDIN_HEADLESS", "true").strip().lower() not in ("0", "false", "no")


def load_profile(engine) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM profile WHERE id = 1")).mappings().first()
    if row is None:
        return None
    profile = dict(row)
    profile["embedding"] = parse_pgvector(profile["embedding"])
    return profile


def main():
    engine = get_engine()
    started_at = datetime.now(timezone.utc)
    new_jobs_found = 0
    errors = []
    blocked = False

    try:
        profile = load_profile(engine)
        if profile is None:
            errors.append("No hay perfil configurado (profile.id=1). Completa el onboarding primero.")
            return
        print(f"Perfil cargado. location_preference={profile.get('location_preference')!r}, remote_preference={profile.get('remote_preference')!r}")

        variants = [v for v in get_all_variants(engine, profile_id=1) if v.get("is_active", True)]
        if not variants:
            errors.append("No hay variantes de busqueda activas.")
            return
        print(f"{len(variants)} variante(s) activa(s) a procesar: {[v['query_text'] for v in variants]}")

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, context = new_browser_context(p, headless=LINKEDIN_HEADLESS)

            for variant in variants:
                if blocked:
                    break
                print(f"\n=== Variante '{variant['query_text']}' (id={variant['id']}) ===")
                page = context.new_page()
                diag_state = attach_diagnostics_listeners(page)
                try:
                    raw_jobs = scrape_variant(
                        page,
                        query_text=variant["query_text"],
                        location=profile.get("location_preference"),
                        remote_preference=profile.get("remote_preference"),
                        hours_ago=LINKEDIN_HOURS_AGO,
                        max_jobs=LINKEDIN_MAX_JOBS_PER_VARIANT,
                        diag_state=diag_state,
                    )
                except LinkedInBlockedError as e:
                    errors.append(f"BLOQUEO de LinkedIn detectado, abortando ejecucion sin reintentar: {e}")
                    blocked = True
                    page.close()
                    break
                except Exception as e:
                    errors.append(f"Error scrapeando variante '{variant['query_text']}': {e}")
                    print(f"  ERROR: {e}")
                    page.close()
                    continue
                finally:
                    if not page.is_closed():
                        page.close()

                inserted_this_variant = 0
                with engine.begin() as conn:
                    for job in raw_jobs:
                        try:
                            _, _, was_inserted = process_and_store_job(
                                conn, job, profile, cutoff=None, errors=errors, variant_id=variant["id"], verbose=True
                            )
                            if was_inserted:
                                new_jobs_found += 1
                                inserted_this_variant += 1
                        except Exception as e:
                            errors.append(f"Error guardando job {job.get('external_id')}: {e}")
                            print(f"  ERROR guardando {job.get('external_id')}: {e}")

                print(f"  Resumen variante: {len(raw_jobs)} scrapeadas, {inserted_this_variant} insertadas como nuevas.")

                time.sleep(random.uniform(5, 12))

            browser.close()

    except Exception:
        errors.append(traceback.format_exc())
    finally:
        _log_run(engine, started_at, new_jobs_found, errors)


def _log_run(engine, started_at, new_jobs_found, errors):
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO run_log (started_at, finished_at, jsearch_calls_used, llm_calls_used, new_jobs_found, errors)
                VALUES (:started_at, :finished_at, 0, 0, :new_jobs_found, :errors)
            """),
            {
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
                "new_jobs_found": new_jobs_found,
                "errors": "\n".join(errors) if errors else None,
            },
        )
    if errors:
        print("\nErrores durante el scraping:", *errors, sep="\n")
    print(f"\nScraping de LinkedIn finalizado. Ofertas nuevas: {new_jobs_found}.")


if __name__ == "__main__":
    main()
