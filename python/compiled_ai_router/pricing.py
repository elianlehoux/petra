"""Precios reales de modelos y cálculo de costo — Fase 1 (medición honesta).

Precios en USD por 1.000.000 de tokens (input/output). Fuente: precios públicos
de OpenAI. Ajustar acá cuando cambien; no hardcodear costos en otro lado.

Si el modelo no está en la tabla, se usa el fallback de config
(TOKEN_COST_INPUT / TOKEN_COST_OUTPUT), que están expresados por 1.000 tokens.
"""

from typing import Optional

# USD por 1M tokens: (input, output)
PRICE_PER_MILLION = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
}


def cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    fallback_input_per_1k: Optional[float] = None,
    fallback_output_per_1k: Optional[float] = None,
) -> float:
    """Costo real de una llamada dado el uso de tokens medido."""
    if model in PRICE_PER_MILLION:
        in_m, out_m = PRICE_PER_MILLION[model]
        return (prompt_tokens * in_m + completion_tokens * out_m) / 1_000_000

    # Fallback a config (precios por 1.000 tokens)
    in_1k = fallback_input_per_1k if fallback_input_per_1k is not None else 0.0
    out_1k = fallback_output_per_1k if fallback_output_per_1k is not None else 0.0
    return (prompt_tokens * in_1k + completion_tokens * out_1k) / 1_000


def is_known_model(model: str) -> bool:
    return model in PRICE_PER_MILLION
