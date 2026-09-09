# linkedinTracker

Sistema autonomo (coste 0 EUR/mes) que busca ofertas de empleo cada 4 horas, las puntua por afinidad
con tu perfil usando embeddings locales + LLM gratuito de OpenRouter, y las expone rankeadas en un
dashboard web.

## Stack

| Capa | Tecnologia | Motivo |
|---|---|---|
| Cron / pipeline | GitHub Actions + Python 3.11 | Gratis, sin worker permanente |
| Base de datos | Supabase Postgres + pgvector | Free tier persistente (500 MB), soporta vectores. Alternativas evaluadas: Neon (free, pausa por inactividad similar) y Render Postgres free (expira a los 30 dias, descartado) |
| Embeddings | sentence-transformers all-MiniLM-L6-v2 (local, CPU) | Gratis, corre en el runner de Actions |
| LLM | OpenRouter, modelos :free (ej. inclusionai/ling-3.0-flash-fin:free) | Extraccion de CV y evaluacion cualitativa, coste 0. |
| Fuente de ofertas | LinkedIn Guest Scraper | Gratuito, sin límites mensuales ni riesgo de baneo |
| Backend + portal | FastAPI + Jinja2 + HTMX | Ligero, sin build de frontend |
| Hosting portal | Render Free Web Service | Gratis; spin-down tras inactividad. NO usar Render Postgres free (expira a 30 dias) |

Nota: Supabase free se pausa tras 7 dias de inactividad total; el cron cada 4h mantiene el proyecto activo.

## Estructura

```
linkedinTracker/
├── .github/workflows/discover_jobs.yml
├── app/
├── pipeline/
├── sql/schema.sql
├── requirements.txt
└── .env.example
```

## Puesta en marcha

1. Crea un proyecto en Supabase, habilita la extension vector y ejecuta sql/schema.sql.
2. Crea cuenta en OpenRouter, genera API key, elige modelo :free vigente.
3. Copia .env.example a .env y rellena variables.
4. pip install -r requirements.txt
5. python app/main.py y abre /onboarding para subir tu CV.
6. python pipeline/run_linkedin_guest.py para probar el scraper.
7. Configura Secrets/Variables en GitHub Actions.
8. Despliega el portal en Render (build: pip install -r requirements.txt; start: uvicorn app.main:app --host 0.0.0.0 --port $PORT).

## Presupuesto de cuotas gratuitas

| Recurso | Limite gratis | Uso planificado | Margen |
|---|---|---|---|
| OpenRouter free | ~20 req/min, 50/dia | 48/dia | 2 |
| GitHub Actions | 2000 min/mes | ~900 min | Amplio |
| Render Free Web | 750h/mes | Esporadico | Amplio |
| Supabase Free | 500 MB | <50MB estimado | Amplio |

## Roadmap v1

Multiusuario, autenticacion, feedback loop, notificaciones, mas fuentes de ofertas.

## Criterios de aceptacion v0

- Subir CV y preferencias, ver JSON extraido.
- Cron corre cada 4h sin superar cuotas.
- Ofertas nuevas con apply_link funcional (parte apuntando a linkedin.com).
- Evaluacion LLM con pros/cons coherentes.
- Fail-soft ante agotamiento de cuotas.
