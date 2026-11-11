"""Configuración global de la plataforma (no la de cada negocio)."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # Token que tú defines y pegas en Meta al registrar el webhook.
    verify_token: str = os.getenv("WA_VERIFY_TOKEN", "cambia-esto")
    # App Secret de tu app de Meta: valida que los webhooks vengan de Meta.
    app_secret: str = os.getenv("WA_APP_SECRET", "")
    graph_api_version: str = os.getenv("WA_GRAPH_VERSION", "v22.0")

    # Modelo de Claude para las respuestas abiertas.
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    # Cuántos mensajes previos enviamos a la IA como contexto.
    history_limit: int = int(os.getenv("HISTORY_LIMIT", "12"))
    # Horas que el bot queda en silencio cuando un humano toma la conversación.
    handoff_hours: float = float(os.getenv("HANDOFF_HOURS", "2"))

    tenants_dir: Path = Path(os.getenv("TENANTS_DIR", "tenants"))
    db_path: str = os.getenv("DB_PATH", "bot.db")


settings = Settings()
