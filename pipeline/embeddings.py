"""
Wrapper de embeddings locales con sentence-transformers.
Se ejecuta dentro del runner de GitHub Actions, sin coste ni llamadas API.
"""
import os
from functools import lru_cache

EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def _sanitize_text(value) -> str:
    """
    Fuerza a str y elimina caracteres invalidos (surrogates sueltos, mojibake)
    que a veces llegan en descripciones agregadas por JSearch desde sitios
    externos. El tokenizer de sentence-transformers (backend en Rust) no da un
    error de decodificacion claro ante esto, sino el mensaje criptico
    'TextEncodeInput must be Union[TextInputSequence, Tuple[...]]'.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.encode("utf-8", errors="ignore").decode("utf-8")


def embed_text(text: str) -> list[float]:
    model = _get_model()
    cleaned = _sanitize_text(text)
    vector = model.encode(cleaned, normalize_embeddings=True)
    return vector.tolist()


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    import numpy as np
    a = np.array(vec_a)
    b = np.array(vec_b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def to_pgvector_literal(vec: list[float]) -> str:
    """Serializa una lista de floats al formato de texto que pgvector espera (ej. '[0.1,0.2,...]')."""
    return "[" + ",".join(repr(float(v)) for v in vec) + "]"


def parse_pgvector(value) -> list[float]:
    """Convierte el valor devuelto por psycopg2 para una columna vector (texto '[0.1,0.2,...]') a list[float]."""
    if value is None:
        return []
    if isinstance(value, str):
        return [float(x) for x in value.strip("[]").split(",") if x]
    return list(value)
