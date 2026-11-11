"""Motor híbrido: menús fijos para lo frecuente, IA para lo abierto.

Flujo de cada mensaje entrante:
  1. ¿Un humano tomó la conversación?  → el bot calla (salvo que pidan "menú").
  2. ¿Eligió una opción del menú?       → respuesta fija, instantánea y gratis.
  3. ¿Saludo / "menú"?                  → mostrar menú principal.
  4. ¿Pide un humano?                   → modo humano.
  5. Cualquier otra cosa                → Claude con los datos del negocio.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Protocol

from .ai import HANDOFF_TOKEN
from .config import settings
from .store import Store
from .tenants import Tenant

log = logging.getLogger(__name__)

MENU_WORDS = {"hola", "menu", "inicio", "buenas", "buenos dias", "buenas tardes",
              "buenas noches", "opciones", "bot"}


class Sender(Protocol):
    def text(self, tenant: Tenant, to: str, body: str) -> None: ...
    def list_menu(self, tenant: Tenant, to: str, body: str, button: str,
                  rows: list[tuple[str, str, str]]) -> None: ...


class Responder(Protocol):
    def reply(self, tenant: Tenant, history: list[dict]) -> str: ...


def normalize(text: str) -> str:
    """Minúsculas, sin acentos ni signos: 'Menú!' → 'menu'."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def to_claude_messages(history: list[dict]) -> list[dict]:
    """La API exige empezar con 'user' y alternar roles: fusionamos consecutivos."""
    msgs: list[dict] = []
    for m in history:
        if not msgs and m["role"] != "user":
            continue
        if msgs and msgs[-1]["role"] == m["role"]:
            msgs[-1]["content"] += "\n" + m["content"]
        else:
            msgs.append(dict(m))
    return msgs


class BotEngine:
    def __init__(self, store: Store, sender: Sender, responder: Responder):
        self.store, self.sender, self.ai = store, sender, responder

    # ---------- punto de entrada ----------
    def handle(self, tenant: Tenant, wa_user: str, text: str = "", choice_id: str = "") -> None:
        norm = normalize(text)

        if self.store.in_handoff(tenant.id, wa_user):
            if norm in {"menu", "bot"}:
                self.store.clear_handoff(tenant.id, wa_user)
                return self._main_menu(tenant, wa_user)
            self._log(tenant, wa_user, "user", text or choice_id)
            return  # lo atiende una persona desde el WhatsApp Business del negocio

        if choice_id:
            self._log(tenant, wa_user, "user", f"(eligió: {choice_id})")
            return self._on_choice(tenant, wa_user, choice_id)

        self._log(tenant, wa_user, "user", text)
        if norm in MENU_WORDS:
            return self._main_menu(tenant, wa_user)
        if any(k in norm.split() for k in map(normalize, tenant.handoff_keywords)):
            return self._handoff(tenant, wa_user)
        self._ask_ai(tenant, wa_user)

    # ---------- menús fijos ----------
    def _main_menu(self, tenant: Tenant, to: str) -> None:
        rows = [
            ("MENU_CATALOG", "🛍️ Ver catálogo", "Productos y precios"),
            ("MENU_ORDER", "📝 Hacer pedido", "Cómo pedir"),
            ("MENU_HOURS", "🕒 Horario", "Cuándo atendemos"),
            ("MENU_LOCATION", "📍 Ubicación", "Dónde estamos"),
            ("MENU_PAYMENTS", "💳 Formas de pago", "Cómo pagar"),
            ("MENU_HUMAN", "🙋 Hablar con alguien", "Te atiende una persona"),
        ]
        self.sender.list_menu(tenant, to, tenant.greeting, "Ver opciones", rows)
        self._log(tenant, to, "assistant", "(mostró menú principal)")

    def _on_choice(self, tenant: Tenant, to: str, choice: str) -> None:
        if choice == "MENU_CATALOG":
            if not tenant.catalog:
                return self._say(tenant, to, "Pronto tendremos el catálogo aquí. 🙌")
            rows = [(f"CAT_{i}", c.name, f"{len(c.items)} productos")
                    for i, c in enumerate(tenant.catalog)]
            self.sender.list_menu(tenant, to, "¿Qué categoría quieres ver?", "Categorías", rows)
            return self._log(tenant, to, "assistant", "(mostró categorías)")
        if choice.startswith("CAT_"):
            idx = int(choice.removeprefix("CAT_"))
            if not 0 <= idx < len(tenant.catalog):
                return self._main_menu(tenant, to)
            cat = tenant.catalog[idx]
            lines = [f"*{cat.name}*"] + [
                f"• {i.name} — {tenant.currency}{i.price:,.2f}" + (f"\n  _{i.description}_" if i.description else "")
                for i in cat.items
            ]
            return self._say(tenant, to, "\n".join(lines) + "\n\n¿Te gustaría pedir algo? Solo escríbelo 😉")
        simple = {
            "MENU_ORDER": tenant.order_instructions,
            "MENU_HOURS": f"🕒 *Horario*\n{tenant.hours}",
            "MENU_LOCATION": f"📍 *Ubicación*\n{tenant.address}\n{tenant.maps_url}".strip(),
            "MENU_PAYMENTS": f"💳 *Formas de pago*\n{tenant.payment_methods}",
        }
        if choice in simple:
            return self._say(tenant, to, simple[choice])
        if choice == "MENU_HUMAN":
            return self._handoff(tenant, to)
        self._main_menu(tenant, to)  # id desconocido (p. ej. menú viejo)

    # ---------- IA y humano ----------
    def _ask_ai(self, tenant: Tenant, to: str) -> None:
        history = to_claude_messages(self.store.history(tenant.id, to, settings.history_limit))
        answer = self.ai.reply(tenant, history)
        if HANDOFF_TOKEN in answer:
            answer = answer.replace(HANDOFF_TOKEN, "").strip()
            if answer:
                self._say(tenant, to, answer)
            return self._handoff(tenant, to)
        self._say(tenant, to, answer)

    def _handoff(self, tenant: Tenant, to: str) -> None:
        self.store.set_handoff(tenant.id, to, settings.handoff_hours)
        self._say(tenant, to, tenant.handoff_message)
        log.info("Handoff a humano: tenant=%s user=%s", tenant.id, to)

    # ---------- utilidades ----------
    def _say(self, tenant: Tenant, to: str, body: str) -> None:
        self.sender.text(tenant, to, body)
        self._log(tenant, to, "assistant", body)

    def _log(self, tenant: Tenant, user: str, role: str, content: str) -> None:
        self.store.add_message(tenant.id, user, role, content)
