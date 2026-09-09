"""
Script de inicialización para bases de datos nuevas (Dev o Pro).
Ejecuta todas las migraciones SQL en orden y crea los usuarios por defecto:
- christian (password: password123)
- sabrina   (password: password456)
junto con sus variantes iniciales de búsqueda.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno desde .env y añadir raíz al path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
load_dotenv()

from sqlalchemy import create_engine, text
from app.auth import hash_password

MIGRATION_FILES = [
    "sql/schema.sql",
    "sql/002_search_query_variant.sql",
    "sql/003_job_score_recommendation.sql",
    "sql/004_job_offer_variant.sql",
    "sql/005_discard_reason.sql",
    "sql/006_salary_raw.sql",
    "sql/007_multi_user.sql",
    "sql/009_enabled_sources.sql",
]

DEFAULT_USERS = [
    {"username": "christian", "password": "password123"},
    {"username": "sabrina", "password": "password456"},
]

DEFAULT_VARIANTS = {
    "christian": [
        "Cloud Architect",
        "AI Solutions Engineer",
        "AI Engineer",
        "AI architect",
    ],
    "sabrina": [
        "psicologa",
        "neuropsicologa",
    ],
}


def main():
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        print("[ERROR] SUPABASE_DB_URL no está definida en .env.")
        sys.exit(1)

    if "[YOUR-PASSWORD]" in db_url or "[YOUR_PASSWORD]" in db_url:
        print("\n" + "=" * 80)
        print("[AVISO IMPORTANTE] SUPABASE_DB_URL contiene '[YOUR-PASSWORD]'.")
        print("Debes sustituir '[YOUR-PASSWORD]' en tu archivo .env por la contraseña real")
        print("que definiste al crear este nuevo proyecto en Supabase (sin corchetes).")
        print("=" * 80 + "\n")
        sys.exit(1)

    print("[*] Conectando a la base de datos...")
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT current_database(), current_user, version();")).fetchone()
            print(f"[OK] Conexión establecida a DB: '{row[0]}' como '{row[1]}'")
    except Exception as e:
        print(f"\n[ERROR] No se pudo conectar a la base de datos: {e}")
        print("Verifica que la URL y la contraseña en .env sean correctas.\n")
        sys.exit(1)

    # 1. Ejecutar archivos SQL con psycopg2 nativo (soporta scripts multi-sentencia con comentarios)
    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        for sql_rel_path in MIGRATION_FILES:
            full_path = root_dir / sql_rel_path
            if not full_path.exists():
                print(f"[WARN] Archivo no encontrado: {sql_rel_path}, saltando.")
                continue

            print(f"[*] Ejecutando {sql_rel_path}...")
            content = full_path.read_text(encoding="utf-8")
            try:
                cur.execute(content)
                raw_conn.commit()
                print(f"    -> {sql_rel_path} completado con éxito.")
            except Exception as sql_err:
                raw_conn.rollback()
                print(f"    [INFO] Error/Aviso al ejecutar {sql_rel_path}: {sql_err}")
                raw_conn.commit()
        cur.close()
    finally:
        raw_conn.close()

    # 2. Crear usuarios por defecto
    user_ids = {}
    with engine.connect() as conn:
        for u in DEFAULT_USERS:
            uname = u["username"]
            pwd = u["password"]
            existing = conn.execute(
                text("SELECT id FROM app_user WHERE username = :uname"),
                {"uname": uname},
            ).fetchone()

            if existing:
                uid = existing[0]
                user_ids[uname] = uid
                print(f"[OK] Usuario '{uname}' ya existe (id={uid}).")
            else:
                p_hash = hash_password(pwd)
                res = conn.execute(
                    text("INSERT INTO app_user (username, password_hash, is_active) VALUES (:uname, :phash, TRUE) RETURNING id"),
                    {"uname": uname, "phash": p_hash},
                )
                uid = res.scalar()
                user_ids[uname] = uid
                print(f"[+] Usuario '{uname}' creado con éxito (id={uid}, password={pwd}).")

        conn.commit()

    # 3. Crear variantes de búsqueda por defecto
    with engine.connect() as conn:
        for uname, variants in DEFAULT_VARIANTS.items():
            uid = user_ids.get(uname)
            if not uid:
                continue

            for idx, q_text in enumerate(variants):
                existing_v = conn.execute(
                    text("SELECT id FROM search_query_variant WHERE user_id = :uid AND query_text = :q"),
                    {"uid": uid, "q": q_text},
                ).fetchone()

                if not existing_v:
                    conn.execute(
                        text("""
                            INSERT INTO search_query_variant (user_id, query_text, source, is_active, order_index)
                            VALUES (:uid, :q, 'manual', TRUE, :idx)
                        """),
                        {"uid": uid, "q": q_text, "idx": idx},
                    )
                    print(f"  [+] Variante agregada para {uname}: '{q_text}'")

        conn.commit()

    print("\n" + "=" * 80)
    print("¡BASE DE DATOS INICIALIZADA CON ÉXITO!")
    print("Usuarios creados:")
    for u in DEFAULT_USERS:
        print(f" - Usuario: {u['username']} | Contraseña: {u['password']}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
