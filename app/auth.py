"""
Módulo de autenticación, hash de contraseñas, sesiones firmadas y control de acceso.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import text

SESSION_COOKIE_NAME = "linkedin_tracker_session"
SESSION_DURATION_SECONDS = 86400 * 14  # 14 días


def get_secret_key() -> str:
    return os.environ.get("APP_SECRET_KEY", "linkedinTracker-secret-key-4a8b9c2d1e0f")


def get_max_users() -> int:
    raw = os.environ.get("MAX_USERS", "2")
    try:
        return max(1, int(raw.strip()))
    except (TypeError, ValueError):
        return 2


def hash_password(password: str) -> str:
    """Genera un hash seguro PBKDF2-HMAC-SHA256 con salt aleatorio."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verifica la contraseña contra el hash almacenado de forma segura frente a timing attacks."""
    try:
        salt, key_hex = stored_hash.split("$", 1)
        expected_key = bytes.fromhex(key_hex)
        computed_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
        return hmac.compare_digest(expected_key, computed_key)
    except Exception:
        return False


def create_session_token(user_id: int, username: str) -> str:
    """Crea un token de sesión firmado criptográficamente con expiración."""
    expires_at = int(time.time()) + SESSION_DURATION_SECONDS
    payload = json.dumps({"uid": user_id, "usr": username, "exp": expires_at}, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")
    sig = hmac.new(get_secret_key().encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_session_token(token: str | None) -> Optional[dict]:
    """Verifica la firma y expiración del token de sesión."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig = token.split(".", 1)
        expected_sig = hmac.new(get_secret_key().encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, sig):
            return None
        payload_json = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
        data = json.loads(payload_json)
        if data.get("exp", 0) < int(time.time()):
            return None
        return data
    except Exception:
        return None


def get_current_user_optional(request: Request) -> Optional[dict]:
    """Obtiene el usuario actual de la cookie de sesión si existe y es válido en la base de datos."""
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    token_data = verify_session_token(cookie)
    if not token_data:
        return None

    user_id = token_data.get("uid")
    from app.db import get_engine
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, username, is_active FROM app_user WHERE id = :id"),
            {"id": user_id},
        ).mappings().first()

    if not row or not row["is_active"]:
        return None

    return {"id": row["id"], "username": row["username"]}


def get_current_user(request: Request) -> dict:
    """
    Dependencia estricta: retorna el usuario logueado o lanza excepción / redirección.
    Si la ruta es de interfaz (dashboard, onboarding, etc.), redirige a /login.
    Si es un endpoint de API (/api/*) o HTMX, responde con error HTTP 401.
    """
    user = get_current_user_optional(request)
    if user:
        return user

    is_api = request.url.path.startswith("/api/") or request.headers.get("hx-request") == "true"
    if not is_api:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": f"/login?next={request.url.path}"},
        )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")



def can_register_user(engine) -> tuple[bool, int, int]:
    """
    Comprueba si aún se pueden registrar usuarios según MAX_USERS.
    Retorna (puede_registrar, total_actual, max_permitido).
    """
    max_users = get_max_users()
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM app_user")).scalar() or 0
    return count < max_users, count, max_users
