"""Cliente para enviar mensajes por la API oficial de WhatsApp Cloud (Meta)."""
from __future__ import annotations

import hashlib
import hmac
import logging

import httpx

from .config import settings
from .tenants import Tenant

log = logging.getLogger(__name__)


def verify_signature(raw_body: bytes, header: str | None, app_secret: str) -> bool:
    """Valida X-Hub-Signature-256 para rechazar webhooks falsificados."""
    if not app_secret:
        log.warning("WA_APP_SECRET vacío: firma NO verificada (solo aceptable en desarrollo)")
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


class WhatsAppSender:
    def __init__(self, client: httpx.Client | None = None):
        self._http = client or httpx.Client(timeout=15)

    def _post(self, tenant: Tenant, to: str, payload: dict) -> None:
        url = f"https://graph.facebook.com/{settings.graph_api_version}/{tenant.phone_number_id}/messages"
        body = {"messaging_product": "whatsapp", "to": to, **payload}
        resp = self._http.post(
            url, json=body, headers={"Authorization": f"Bearer {tenant.access_token}"}
        )
        if resp.is_error:
            log.error("WhatsApp API %s [%s]: %s", resp.status_code, tenant.id, resp.text)
        resp.raise_for_status()

    def text(self, tenant: Tenant, to: str, body: str) -> None:
        self._post(tenant, to, {"type": "text", "text": {"body": body[:4096]}})

    def list_menu(
        self, tenant: Tenant, to: str, body: str, button: str, rows: list[tuple[str, str, str]]
    ) -> None:
        """Lista interactiva. rows = [(id, título ≤24, descripción ≤72)], máx. 10."""
        self._post(tenant, to, {
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body[:1024]},
                "action": {
                    "button": button[:20],
                    "sections": [{
                        "title": "Opciones",
                        "rows": [
                            {"id": i, "title": t[:24], "description": d[:72]}
                            for i, t, d in rows[:10]
                        ],
                    }],
                },
            },
        })
