"""Respuestas abiertas con Claude, usando los datos de cada negocio."""
from __future__ import annotations

import logging

import anthropic

from .config import settings
from .tenants import Tenant

log = logging.getLogger(__name__)

HANDOFF_TOKEN = "[[HUMANO]]"
FALLBACK_REPLY = "Disculpa, no pude procesar tu mensaje. Escribe *menú* para ver las opciones."


def build_system_prompt(t: Tenant) -> str:
    """Prompt estable por negocio (sin fechas ni datos variables → se cachea bien)."""
    catalog = "\n".join(
        f"## {c.name}\n" + "\n".join(
            f"- {i.name}: {t.currency}{i.price:,.2f}" + (f" — {i.description}" if i.description else "")
            for i in c.items
        )
        for c in t.catalog
    )
    faq = "\n".join(f"P: {f['q']}\nR: {f['a']}" for f in t.faq)
    return f"""Eres el asistente de WhatsApp de "{t.name}". Tono: {t.tone}.

Reglas:
- Responde SOLO con la información de abajo. Si no sabes algo, no lo inventes:
  ofrece pasar con una persona.
- Mensajes cortos (máx. ~5 líneas), aptos para WhatsApp. Usa *negritas* de WhatsApp, no Markdown.
- Nunca inventes precios, productos, promociones ni horarios.
- Si el cliente quiere hacer un pedido, ayúdale a armarlo (productos, cantidades,
  total aproximado) y al final indica: {t.order_instructions}
- Si el cliente pide hablar con una persona, está molesto, o la pregunta requiere a
  alguien del negocio (reclamos, pagos, casos especiales), escribe una frase breve y
  termina tu respuesta con {HANDOFF_TOKEN}
- Si no aplica nada de lo anterior, puedes recordarle que escriba *menú* para ver opciones.

# Información del negocio
Horario: {t.hours}
Dirección: {t.address} {t.maps_url}
Formas de pago: {t.payment_methods}
{t.extra_info}

# Catálogo
{catalog or "(sin catálogo cargado)"}

# Preguntas frecuentes
{faq or "(sin FAQ)"}
"""


class ClaudeResponder:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self._client = client or anthropic.Anthropic()
        self._prompts: dict[str, str] = {}

    def reply(self, tenant: Tenant, history: list[dict]) -> str:
        system = self._prompts.setdefault(tenant.id, build_system_prompt(tenant))
        try:
            response = self._client.beta.messages.create(
                model=settings.claude_model,
                max_tokens=2048,  # respuestas de WhatsApp: deliberadamente cortas
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=history,
                output_config={"effort": "low"},  # chat simple: menor latencia y costo
                # Si el modelo rechaza la petición, la API reintenta con otro modelo.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError:
            log.warning("Claude rate limit [%s]", tenant.id)
            return FALLBACK_REPLY
        except anthropic.APIStatusError as e:
            log.error("Claude API %s [%s]: %s", e.status_code, tenant.id, e.message)
            return FALLBACK_REPLY
        except anthropic.APIConnectionError:
            log.error("Claude sin conexión [%s]", tenant.id)
            return FALLBACK_REPLY

        if response.stop_reason == "refusal":
            return FALLBACK_REPLY
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or FALLBACK_REPLY
