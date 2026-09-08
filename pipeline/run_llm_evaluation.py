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
LLM_MAX_CONSECUTIVE_ERRORS = max(1, _int_env("LLM_MAX_CONSECUTIVE_ERRORS", 3))


def load_profile(engine) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM profile WHERE id = 1")).mappings().first()
    if row is None:
        return None
    profile = dict(row)
    profile["embedding"] = parse_pgvector(profile["embedding"])
    return profile


def _render_summary_table(items: list[dict], user_stats: dict, total_pending_remaining: int, total_duration: float) -> str:
    lines = [
        "=" * 86,
        "RESUMEN DE EVALUACIÓN CUALITATIVA CON LLM",
        "=" * 86,
        f"{'Usuario':<15} | {'Total':<6} | {'Apply (🌟)':<12} | {'Consider (🔍)':<14} | {'Skip (❌)':<10} | {'Errores':<8}",
        "-" * 86,
    ]
    tot_eval = sum(s["total"] for s in user_stats.values())
    tot_apply = sum(s["apply"] for s in user_stats.values())
    tot_consider = sum(s["consider"] for s in user_stats.values())
    tot_skip = sum(s["skip"] for s in user_stats.values())
    tot_err = sum(s["errors"] for s in user_stats.values())

    for uname, s in sorted(user_stats.items()):
        lines.append(
            f"{uname:<15} | {s['total']:<6} | {s['apply']:<12} | {s['consider']:<14} | {s['skip']:<10} | {s['errors']:<8}"
        )
    lines.append("-" * 86)
    lines.append(
        f"{'TOTAL':<15} | {tot_eval:<6} | {tot_apply:<12} | {tot_consider:<14} | {tot_skip:<10} | {tot_err:<8}"
    )
    lines.append(
        f"Ofertas pendientes restantes en BD: {total_pending_remaining} | Tiempo total: {total_duration:.1f}s"
    )
    lines.append("=" * 86)
    return "\n".join(lines)


def _write_github_step_summary(items: list[dict], user_stats: dict, total_pending_remaining: int, total_duration: float, circuit_breaker_triggered: bool = False):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    try:
        md = []
        md.append("## 🤖 Resumen de Evaluación LLM\n")
        if circuit_breaker_triggered:
            md.append("> [!CAUTION]\n> **🛑 EJECUCIÓN DETENIDA POR CIRCUIT BREAKER:** Fallos consecutivos repetidos al conectar con el LLM. Se ha detenido la ejecución para evitar esperas inútiles. Las ofertas evaluadas antes del fallo se han guardado correctamente.\n")
        md.append(f"> **Duración total:** `{total_duration:.1f}s` | **Pendientes restantes en BD:** `{total_pending_remaining}`\n")

        # Tabla por usuario
        md.append("### 👥 Métricas por Usuario\n")
        md.append("| Usuario | Evaluadas | 🌟 Apply | 🔍 Consider | ❌ Descartadas (Skip) | Errores |")
        md.append("| :--- | :---: | :---: | :---: | :---: | :---: |")
        for uname, s in sorted(user_stats.items()):
            md.append(f"| **{uname}** | {s['total']} | {s['apply']} | {s['consider']} | {s['skip']} | {s['errors']} |")

        tot_eval = sum(s["total"] for s in user_stats.values())
        tot_apply = sum(s["apply"] for s in user_stats.values())
        tot_consider = sum(s["consider"] for s in user_stats.values())
        tot_skip = sum(s["skip"] for s in user_stats.values())
        tot_err = sum(s["errors"] for s in user_stats.values())
        md.append(f"| **TOTAL** | **{tot_eval}** | **{tot_apply}** | **{tot_consider}** | **{tot_skip}** | **{tot_err}** |\n")

        # Tabla de ofertas evaluadas
        if items:
            md.append("### 📋 Ofertas Procesadas en esta Ejecución\n")
            md.append("| # | Usuario | Oferta | Empresa | Score | Decisión | Salario | Tiempo |")
            md.append("| :---: | :--- | :--- | :--- | :---: | :---: | :--- | :---: |")
            for it in items:
                dec_icon = "🌟 **Apply**" if it["recommendation"] == "apply" else ("❌ *Skip*" if it["recommendation"] == "skip" else "🔍 Consider")
                sal_txt = it.get("salary") or "-"
                md.append(
                    f"| {it['job_id']} | `{it['user']}` | {it['title']} | {it['company']} | `{it['score']:.0f}` | {dec_icon} | {sal_txt} | `{it['duration']:.1f}s` |"
                )
            md.append("")

        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
    except Exception as e:
        print(f"[run_llm_evaluation] No se pudo escribir GITHUB_STEP_SUMMARY: {e}", flush=True)


def main():
    engine = get_engine()
    started_at = datetime.now(timezone.utc)
    llm_calls = 0
    errors = []
    evaluated_items = []
    user_stats = {}
    consecutive_errors = 0
    circuit_breaker_triggered = False

    try:
        with engine.connect() as conn:
            # Contar total de pendientes en BD
            total_pending_in_db = conn.execute(
                text("SELECT COUNT(*) FROM job_score WHERE llm_evaluated = FALSE")
            ).scalar() or 0

            pending = conn.execute(
                text("""
                    SELECT js.id AS score_id, js.job_offer_id, js.vector_similarity, js.user_id,
                           COALESCE(u.username, 'user_' || js.user_id) AS username,
                           p.extracted_json AS profile_json, p.remote_preference, p.min_salary, p.excluded_keywords,
                           jo.*
                    FROM job_score js
                    JOIN job_offer jo ON jo.id = js.job_offer_id
                    LEFT JOIN app_user u ON u.id = js.user_id
                    JOIN profile p ON (p.id = js.profile_id OR p.user_id = js.user_id)
                    WHERE js.llm_evaluated = FALSE
                    ORDER BY js.vector_similarity DESC
                    LIMIT :limit
                """),
                {"limit": LLM_MAX_CALLS_PER_RUN},
            ).mappings().all()

        total_to_process = len(pending)
        print("\n" + "=" * 86, flush=True)
        print("🚀 INICIO DE EVALUACIÓN CUALITATIVA CON LLM (OpenRouter)", flush=True)
        print("=" * 86, flush=True)
        print(f"📊 Ofertas pendientes totales en BD: {total_pending_in_db}", flush=True)
        print(f"🎯 Tanda seleccionada para evaluar:  {total_to_process} (tope: {LLM_MAX_CALLS_PER_RUN})", flush=True)
        print(f"⏱️  Pausa entre llamadas:            {LLM_CALL_DELAY_SECONDS}s", flush=True)
        print("=" * 86 + "\n", flush=True)

        if not pending:
            print("✨ No hay ofertas pendientes de evaluación LLM en este momento.", flush=True)

        for i, row in enumerate(pending):
            uname = row["username"]
            if uname not in user_stats:
                user_stats[uname] = {"total": 0, "apply": 0, "consider": 0, "skip": 0, "errors": 0}

            job_title = row.get("title") or "Sin título"
            company = row.get("company") or "Confidencial"
            progress_pct = int(((i + 1) / total_to_process) * 100)

            print(
                f"[{i + 1}/{total_to_process}] ({progress_pct}%) ⏳ Evaluando job #{row['job_offer_id']} "
                f"[{uname}] \"{job_title}\" @ {company}...",
                flush=True,
            )

            t0 = time.time()
            user_profile = {
                "extracted_json": row["profile_json"],
                "remote_preference": row["remote_preference"],
                "min_salary": row["min_salary"],
                "excluded_keywords": row["excluded_keywords"],
            }

            try:
                evaluation = evaluate_job_with_llm(user_profile["extracted_json"], dict(row), profile_meta=user_profile)
                llm_calls += 1
            except Exception as e:
                dur = time.time() - t0
                err_msg = f"LLM error en job #{row['job_offer_id']} ({uname}): {e}"
                errors.append(err_msg)
                user_stats[uname]["errors"] += 1
                consecutive_errors += 1
                print(f"       ⚠️  ERROR ({dur:.1f}s): {e}", flush=True)

                if consecutive_errors >= LLM_MAX_CONSECUTIVE_ERRORS:
                    circuit_breaker_triggered = True
                    circuit_msg = (
                        f"🛑 CIRCUIT BREAKER ACTIVADO: {consecutive_errors} llamadas consecutivas al LLM han fallado. "
                        "El proveedor o modelo no responde adecuadamente. Se detiene la ejecución para evitar esperas inútiles."
                    )
                    print("\n" + "!" * 86, flush=True)
                    print(circuit_msg, flush=True)
                    print("!" * 86 + "\n", flush=True)
                    errors.append(circuit_msg)
                    break

                if LLM_CALL_DELAY_SECONDS > 0 and i < total_to_process - 1:
                    time.sleep(LLM_CALL_DELAY_SECONDS)
                continue

            consecutive_errors = 0

            dur = time.time() - t0
            hard_score = hard_requirements_score(user_profile, dict(row))
            recommendation = evaluation.get("recommendation", "consider")
            final_score = compute_final_score(row["vector_similarity"], hard_score, evaluation["llm_score"], recommendation=recommendation)

            is_skip = (recommendation == "skip")
            new_status = "discarded" if is_skip else (row.get("status") or "new")

            discard_reason = None
            if is_skip:
                missing = evaluation.get("missing_requirements") or []
                discard_reason = f"Descarte automático IA: {missing[0]}" if missing else "Requisitos mínimos o años de experiencia no cumplidos."
                user_stats[uname]["skip"] += 1
                print(f"       ❌ [SKIP] ({dur:.1f}s) Score: {final_score:.0f} | Motivo: {discard_reason}", flush=True)
            elif recommendation == "apply":
                user_stats[uname]["apply"] += 1
                print(f"       🌟 [APPLY] ({dur:.1f}s) Score: {final_score:.0f} | Cumple perfil", flush=True)
            else:
                user_stats[uname]["consider"] += 1
                print(f"       🔍 [CONSIDER] ({dur:.1f}s) Score: {final_score:.0f}", flush=True)

            user_stats[uname]["total"] += 1

            extracted_salary = evaluation.get("salary")
            if extracted_salary:
                print(f"          💰 Salario detectado: '{extracted_salary}'", flush=True)

            evaluated_items.append({
                "job_id": row["job_offer_id"],
                "user": uname,
                "title": job_title,
                "company": company,
                "recommendation": recommendation,
                "score": final_score,
                "salary": extracted_salary,
                "duration": dur,
            })

            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE job_score SET 
                            llm_score = :llm_score, 
                            llm_evaluated = TRUE,
                            pros = :pros, 
                            cons = :cons, 
                            missing_requirements = :missing,
                            recommendation = :recommendation, 
                            final_score = :final_score,
                            status = :status,
                            discard_reason = COALESCE(discard_reason, :discard_reason)
                        WHERE id = :score_id
                    """),
                    {
                        "llm_score": evaluation["llm_score"],
                        "pros": evaluation["pros"],
                        "cons": evaluation["cons"],
                        "missing": evaluation["missing_requirements"],
                        "recommendation": recommendation,
                        "final_score": final_score,
                        "status": new_status,
                        "discard_reason": discard_reason,
                        "score_id": row["score_id"],
                    },
                )

                if extracted_salary:
                    conn.execute(
                        text("""
                            UPDATE job_offer SET salary_raw = :salary
                            WHERE id = :job_offer_id AND (salary_raw IS NULL OR salary_raw = '')
                        """),
                        {"salary": extracted_salary, "job_offer_id": row["job_offer_id"]},
                    )

            if LLM_CALL_DELAY_SECONDS > 0 and i < total_to_process - 1:
                time.sleep(LLM_CALL_DELAY_SECONDS)

        if total_to_process >= LLM_MAX_CALLS_PER_RUN:
            errors.append(
                f"Se alcanzó el tope LLM_MAX_CALLS_PER_RUN={LLM_MAX_CALLS_PER_RUN} en esta ejecución. "
                "Las ofertas restantes se evaluarán en la próxima tanda."
            )

    except Exception:
        errors.append(traceback.format_exc())
    finally:
        total_duration = (datetime.now(timezone.utc) - started_at).total_seconds()
        
        # Calcular restantes reales
        remaining_pending = 0
        try:
            with engine.connect() as conn:
                remaining_pending = conn.execute(
                    text("SELECT COUNT(*) FROM job_score WHERE llm_evaluated = FALSE")
                ).scalar() or 0
        except Exception:
            pass

        summary_table = _render_summary_table(evaluated_items, user_stats, remaining_pending, total_duration)
        print("\n" + summary_table + "\n", flush=True)

        _write_github_step_summary(evaluated_items, user_stats, remaining_pending, total_duration, circuit_breaker_triggered=circuit_breaker_triggered)
        _log_run(engine, started_at, llm_calls, errors, summary_table=summary_table)


def _log_run(engine, started_at, llm_calls, errors, summary_table: str | None = None):
    log_content = []
    if summary_table:
        log_content.append(summary_table)
    if errors:
        log_content.append("INCIDENCIAS:\n" + "\n".join(errors))

    try:
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
                    "errors": "\n\n".join(log_content) if log_content else None,
                },
            )
    except Exception as e:
        print(f"[run_llm_evaluation] No se pudo escribir run_log: {e}", flush=True)

    if errors:
        print(f"⚠️  Incidencias registradas ({len(errors)}):", *errors[:5], sep="\n  * ", flush=True)
    print(f"✅ Evaluación LLM finalizada con éxito. Llamadas realizadas: {llm_calls}.\n", flush=True)


if __name__ == "__main__":
    main()

