-- El LLM ya calculaba una recomendacion (apply/consider/skip) al evaluar cada oferta,
-- pero se descartaba sin persistir ni usarse para nada. Esta columna la guarda para
-- poder excluir del dashboard las ofertas que incumplen claramente un requisito duro
-- (anios de experiencia, certificacion obligatoria, idioma obligatorio, etc.).

ALTER TABLE job_score ADD COLUMN IF NOT EXISTS recommendation TEXT;

COMMENT ON COLUMN job_score.recommendation IS
    'apply | consider | skip. Calculado por el LLM en evaluate_job_with_llm(). skip = incumple un requisito duro explicito de la oferta; se excluye del dashboard por defecto.';
