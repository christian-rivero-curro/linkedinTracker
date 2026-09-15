#!/usr/bin/env bash
# ==============================================================================
# Script para lanzar linkedinTracker en local
# Activa el entorno virtual (.venv) si existe (o lo crea) y arranca app/main.py
# ==============================================================================

set -e

# Asegurar que estamos en el directorio raíz del proyecto
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "🚀 Iniciando linkedinTracker..."

# Comprobar o inicializar el entorno virtual
if [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
    echo "📦 Activando entorno virtual existente (.venv)..."
    source .venv/bin/activate
elif [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
    echo "📦 Activando entorno virtual existente (venv)..."
    source venv/bin/activate
else
    echo "⚠️  No se encontró un entorno virtual (.venv)."
    echo "🔧 Creando nuevo entorno virtual con python3..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "📥 Instalando dependencias de requirements.txt..."
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# Comprobar archivo de configuración .env
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "⚠️  No se encontró .env. Creando una copia desde .env.example..."
        cp .env.example .env
        echo "ℹ️  Revisa y configura las variables en tu archivo .env si es necesario."
    else
        echo "⚠️  Aviso: No se encontró archivo .env."
    fi
fi

# Comprobar o levantar contenedor de base de datos PostgreSQL local
if command -v docker &> /dev/null; then
    if ! docker ps --filter "name=linkedin-tracker-db" --format "{{.Names}}" | grep -q "linkedin-tracker-db"; then
        echo "🐘 Levantando contenedor de base de datos (PostgreSQL + pgvector)..."
        docker compose -f docker-compose.db.yml up -d
        # Breve espera para que postgres esté listo para conexiones
        sleep 2
    else
        echo "🐘 Base de datos local (linkedin-tracker-db) ya está activa."
    fi
fi

# Lanzar la aplicación
echo "✨ Ejecutando app/main.py..."
python app/main.py
