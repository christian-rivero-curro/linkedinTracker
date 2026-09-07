"""
Evalua con el LLM todas las ofertas pendientes (job_score.llm_evaluated = FALSE),
sin esperar al ciclo de descubrimiento de JSearch (que sigue siendo cada 4h
porque esa cuota si es limitada de verdad).

Este script esta pensado para ejecutarse con mucha mas frecuencia (cada 5
minutos via GitHub Actions, el minimo real que admite su sintaxis de cron) ya
que el modelo de OpenRouter usado es :free y la cuenta actual no tiene un
limite diario real. El unico motivo para no lanzar las llamadas en bucle sin
pausa es evitar el rate-limit POR MINUTO del proveedor, por eso se deja
LLM_CALL_DELAY_SECONDS (default 2s) entre llamada y llamada - es un margen de
seguridad frente a ese rate-limit, no un intento de ahorrar coste.

No se filtra por vector_similarity: TODA oferta pendiente debe acabar teniendo
un resumen del LLM (norma del producto), simplemente se prioriza por mayor
similitud vectorial primero dentro de cada tanda. Un filtro de similitud
minima tenia sentido cuando el LLM era un recurso escaso/de pago; ya no lo es.

LLM_MAX_CALLS_PER_RUN actua como valvula de seguridad para que una sola
ejecucion no se alargue indefinidamente (por ejemplo si hay un backlog
enorme) y quede dentro del timeout del job de GitHub Actions; lo que no
quepa en esta tanda se recoge en la siguiente ejecucion 5 minutos despues.

Fail-soft: nunca debe terminar con excepcion no controlada.
"""
import os
import sys
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_engine  # noqa: E402
from pipeline.embeddings import parse_pgvector  # noqa: E402
from pipeline.scoring import hard_requirements_score, evaluate_job_with_llm, compute_final_score  # noqa: E402


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        print(f"[run_llm_evaluation] Valor invalido para {name}='{raw}', usando default {default}.")
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        print(f"[run_llm_evaluation] Valor invalido para {name}='{raw}', usando default {default}.")
        return default


LLM_CALL_DELAY_SECONDS = max(0.0, _float_env("LLM_CALL_DELAY_SECONDS", 2.0))
LLM_MAX_CALLS_PER_RUN = max(1, _int_env("LLM_MAX_CALLS_PER_RUN", 100))


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
    llm_calls = 0
    errors = []

    try:
        profile = load_profile(engine)
        if profile is None:
            errors.append("No hay perfil configurado (profile.id=1). Completa el onboarding primero.")
            return

        with engine.connect() as conn:
            pending = conn.execute(
                text("""
                    SELECT js.id AS score_id, js.job_offer_id, js.vector_similarity, jo.*
                    FROM job_score js
                    JOIN job_offer jo ON jo.id = js.job_offer_id
                    WHERE js.llm_evaluated = FALSE
                    ORDER BY js.vector_similarity DESC
                    LIMIT :limit
                """),
                {"limit": LLM_MAX_CALLS_PER_RUN},
            ).mappings().all()

        if not pending:
            print("Sin ofertas pendientes de evaluacion LLM en este momento.")

        for i, row in enumerate(pending):
            try:
                evaluation = evaluate_job_with_llm(profile["extracted_json"], dict(row))
                llm_calls += 1
            except Exception as e:
                errors.append(f"LLM error en job {row['job_offer_id']}: {e}")
                if LLM_CALL_DELAY_SECONDS > 0 and i < len(pending) - 1:
                    time.sleep(LLM_CALL_DELAY_SECONDS)
                continue

            hard_score = hard_requirements_score(profile, dict(row))
            final_score = compute_final_score(row["vector_similarity"], hard_score, evaluation["llm_score"])

            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE job_score SET llm_score = :llm_score, llm_evaluated = TRUE,
                            pros = :pros, cons = :cons, missing_requirements = :missing,
                            recommendation = :recommendation, final_score = :final_score
                        WHERE id = :score_id
                    """),
                    {
                        "llm_score": evaluation["llm_score"],
                        "pros": evaluation["pros"],
                        "cons": evaluation["cons"],
                        "missing": evaluation["missing_requirements"],
                        "recommendation": evaluation["recommendation"],
                        "final_score": final_score,
                        "score_id": row["score_id"],
                    },
                )

            if LLM_CALL_DELAY_SECONDS > 0 and i < len(pending) - 1:
                time.sleep(LLM_CALL_DELAY_SECONDS)

        if len(pending) >= LLM_MAX_CALLS_PER_RUN:
            errors.append(
                f"Se alcanzo el tope de seguridad LLM_MAX_CALLS_PER_RUN={LLM_MAX_CALLS_PER_RUN} en esta ejecucion; "
                "puede quedar backlog para la proxima tanda (dentro de unos minutos)."
            )

    except Exception:
        errors.append(traceback.format_exc())
    finally:
        _log_run(engine, started_at, llm_calls, errors)


def _log_run(engine, started_at, llm_calls, errors):
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO run_log (started_at, finished_at, jsearch_calls_used, llm_calls_used, new_jobs_found, errors)
                VALUES (:started_at, :finished_at, 0, :llm_calls, 0, :errors)
            """),
            {
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
                "llm_calls": llm_calls,
                "errors": "\n".join(errors) if errors else None,
            },
        )
    if errors:
        print("Errores durante la evaluacion:", *errors, sep="\n")
    print(f"Evaluacion LLM finalizada. LLM calls: {llm_calls}.")


if __name__ == "__main__":
    main()
