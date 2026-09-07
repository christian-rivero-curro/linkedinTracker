"""
Ejecutar UNA VEZ en local (headed, fuera de Docker) para generar la sesion
guardada que despues usara el contenedor en headless.

LinkedIn trata los logins repetidos como una senal fuerte de automatizacion;
por eso la sesion se genera a mano una vez y se reutiliza en cada ejecucion
posterior del scraper, en vez de loguearse por script en cada corrida.

Uso:
    python pipeline/linkedin_login.py

Se abre un Chromium visible. Inicia sesion a mano (incluida cualquier
verificacion en dos pasos) y vuelve a la terminal cuando veas tu feed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

STORAGE_STATE_PATH = os.environ.get("LINKEDIN_STORAGE_STATE", "linkedin_session/storage_state.json")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def main():
    directory = os.path.dirname(STORAGE_STATE_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=DEFAULT_USER_AGENT,
            locale="es-ES",
            timezone_id="Europe/Madrid",
        )
        Stealth().apply_stealth_sync(context)
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")
        print("Inicia sesion manualmente en la ventana del navegador (incluyendo 2FA si aplica).")
        input("Cuando veas tu feed de LinkedIn, pulsa ENTER aqui para guardar la sesion...")
        context.storage_state(path=STORAGE_STATE_PATH)
        print(f"Sesion guardada en {STORAGE_STATE_PATH}")
        browser.close()


if __name__ == "__main__":
    main()
