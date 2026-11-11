"""Carga la configuración de cada negocio (tenant) desde archivos YAML.

Cada cliente que le vendes = un archivo en tenants/. El bot identifica a qué
negocio va dirigido un mensaje por el `phone_number_id` que manda Meta.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class CatalogItem:
    name: str
    price: float
    description: str = ""


@dataclass
class Category:
    name: str
    items: list[CatalogItem]


@dataclass
class Tenant:
    id: str
    name: str
    phone_number_id: str
    token_env: str  # nombre de la variable de entorno con el token (nunca el token en el YAML)
    greeting: str
    hours: str
    address: str
    payment_methods: str
    currency: str = "$"
    tone: str = "amable, cercano y breve"
    maps_url: str = ""
    order_instructions: str = "Escríbenos tu pedido y te lo confirmamos en un momento."
    catalog: list[Category] = field(default_factory=list)
    faq: list[dict] = field(default_factory=list)
    extra_info: str = ""
    handoff_keywords: list[str] = field(default_factory=lambda: ["humano", "asesor", "persona"])
    handoff_message: str = "Te comunico con alguien del equipo, en breve te responden. 🙌"

    @property
    def access_token(self) -> str:
        token = os.getenv(self.token_env, "")
        if not token:
            raise RuntimeError(f"Falta la variable de entorno {self.token_env} para '{self.id}'")
        return token


def _parse(data: dict) -> Tenant:
    catalog = [
        Category(c["name"], [CatalogItem(**i) for i in c.get("items", [])])
        for c in data.pop("catalog", [])
    ]
    return Tenant(catalog=catalog, **data)


class TenantRegistry:
    def __init__(self, directory: Path):
        self._by_phone: dict[str, Tenant] = {}
        for path in sorted(directory.glob("*.y*ml")):
            tenant = _parse(yaml.safe_load(path.read_text(encoding="utf-8")))
            if tenant.phone_number_id in self._by_phone:
                raise ValueError(f"phone_number_id duplicado en {path.name}")
            self._by_phone[tenant.phone_number_id] = tenant

    def by_phone_number_id(self, phone_number_id: str) -> Tenant | None:
        return self._by_phone.get(phone_number_id)

    def __len__(self) -> int:
        return len(self._by_phone)
