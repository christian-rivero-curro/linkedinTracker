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
| LLM | OpenRouter, modelos :free (ej. minimax/minimax-m2.7:free) | Extraccion de CV y evaluacion cualitativa, coste 0. Verificar disponibilidad vigente en openrouter.ai/models?max_price=0 |
| Fuente de ofertas | JSearch API (RapidAPI, free tier 200 req/mes) | Agrega LinkedIn/Indeed, enlace directo |
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
3. Crea cuenta en RapidAPI y suscribete al free tier de JSearch.
4. Copia .env.example a .env y rellena variables.
5. pip install -r requirements.txt
6. python app/main.py y abre /onboarding para subir tu CV.
7. python pipeline/run_discovery.py para probar el pipeline.
8. Configura Secrets/Variables en GitHub Actions.
9. Despliega el portal en Render (build: pip install -r requirements.txt; start: uvicorn app.main:app --host 0.0.0.0 --port $PORT).

## Presupuesto de cuotas gratuitas

| Recurso | Limite gratis | Uso planificado | Margen |
|---|---|---|---|
| JSearch | 200 req/mes | 180 | 20 |
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
