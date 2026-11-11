"""Servidor FastAPI: un solo webhook atiende a TODOS los negocios."""
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .ai import ClaudeResponder
from .config import settings
from .engine import BotEngine
from .store import Store
from .tenants import TenantRegistry
from .whatsapp import WhatsAppSender, verify_signature

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

app = FastAPI(title="WhatsApp Bot multi-negocio")
tenants = TenantRegistry(settings.tenants_dir)
store = Store(settings.db_path)
engine = BotEngine(store, WhatsAppSender(), ClaudeResponder())
log.info("Negocios cargados: %d", len(tenants))


@app.get("/health")
def health():
    return {"ok": True, "tenants": len(tenants)}


@app.get("/webhook")
def verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    """Meta llama aquí una vez al registrar el webhook."""
    if mode == "subscribe" and token == settings.verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(403, "Token de verificación inválido")


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256"), settings.app_secret):
        raise HTTPException(401, "Firma inválida")

    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            tenant = tenants.by_phone_number_id(value.get("metadata", {}).get("phone_number_id", ""))
            if not tenant:
                continue  # número no registrado (o evento de otra app)
            for msg in value.get("messages", []):  # 'statuses' (entregado/leído) se ignoran
                if not store.mark_processed(msg["id"]):
                    continue
                text, choice = _extract(msg)
                if text or choice:
                    # Respondemos 200 a Meta de inmediato y procesamos en segundo plano;
                    # si tardamos, Meta reintenta y duplica mensajes.
                    background.add_task(_safe_handle, tenant, msg["from"], text, choice)
                else:
                    background.add_task(_safe_unsupported, tenant, msg["from"])
    return {"status": "ok"}


def _extract(msg: dict) -> tuple[str, str]:
    kind = msg.get("type")
    if kind == "text":
        return msg["text"]["body"], ""
    if kind == "interactive":
        inter = msg["interactive"]
        reply = inter.get("list_reply") or inter.get("button_reply") or {}
        return "", reply.get("id", "")
    if kind == "button":  # botones de plantillas
        return msg["button"].get("text", ""), ""
    return "", ""  # audio, imagen, sticker... (ver "siguientes pasos" en README)


def _safe_handle(tenant, wa_user, text, choice):
    try:
        engine.handle(tenant, wa_user, text=text, choice_id=choice)
    except Exception:
        log.exception("Error procesando mensaje tenant=%s user=%s", tenant.id, wa_user)


def _safe_unsupported(tenant, wa_user):
    try:
        engine.sender.text(tenant, wa_user, "Por ahora solo leo mensajes de texto ✍️. Escribe *menú* para ver opciones.")
    except Exception:
        log.exception("Error enviando aviso tenant=%s", tenant.id)
