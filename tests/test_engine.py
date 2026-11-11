"""Pruebas del motor híbrido con dobles falsos (sin Meta ni Claude reales)."""
import hashlib
import hmac
from pathlib import Path

import pytest

from app.ai import HANDOFF_TOKEN, build_system_prompt
from app.engine import BotEngine, normalize, to_claude_messages
from app.store import Store
from app.tenants import TenantRegistry
from app.whatsapp import verify_signature

TENANTS = Path(__file__).parent.parent / "tenants"
USER = "5215511112222"


class FakeSender:
    def __init__(self):
        self.sent = []

    def text(self, tenant, to, body):
        self.sent.append(("text", body))

    def list_menu(self, tenant, to, body, button, rows):
        self.sent.append(("list", [r[0] for r in rows]))


class FakeAI:
    def __init__(self, answer="Claro, la Margarita cuesta $149."):
        self.answer, self.calls = answer, []

    def reply(self, tenant, history):
        self.calls.append(history)
        return self.answer


@pytest.fixture
def tenant():
    return TenantRegistry(TENANTS).by_phone_number_id("123456789012345")


@pytest.fixture
def bot(tmp_path):
    return BotEngine(Store(str(tmp_path / "t.db")), FakeSender(), FakeAI())


def test_greeting_shows_menu_without_ai(bot, tenant):
    bot.handle(tenant, USER, text="¡Hola!")
    assert bot.sender.sent[-1][0] == "list"
    assert bot.ai.calls == []  # los saludos no gastan IA


def test_catalog_flow(bot, tenant):
    bot.handle(tenant, USER, choice_id="MENU_CATALOG")
    assert bot.sender.sent[-1] == ("list", ["CAT_0", "CAT_1"])
    bot.handle(tenant, USER, choice_id="CAT_0")
    assert "Margarita" in bot.sender.sent[-1][1] and "$149.00" in bot.sender.sent[-1][1]


def test_open_question_goes_to_ai_with_valid_history(bot, tenant):
    bot.handle(tenant, USER, text="hola")
    bot.handle(tenant, USER, text="¿cuánto cuesta la margarita?")
    history = bot.ai.calls[-1]
    assert history[0]["role"] == "user" and history[-1]["role"] == "user"
    assert all(a["role"] != b["role"] for a, b in zip(history, history[1:]))


def test_handoff_silences_bot_until_menu(bot, tenant):
    bot.handle(tenant, USER, text="quiero hablar con un asesor")
    assert "equipo" in bot.sender.sent[-1][1]
    n = len(bot.sender.sent)
    bot.handle(tenant, USER, text="¿siguen ahí?")
    assert len(bot.sender.sent) == n  # el bot no interrumpe al humano
    bot.handle(tenant, USER, text="menú")
    assert bot.sender.sent[-1][0] == "list"


def test_ai_can_trigger_handoff(tmp_path, tenant):
    bot = BotEngine(Store(str(tmp_path / "t.db")), FakeSender(),
                    FakeAI(f"Lo reviso con el equipo. {HANDOFF_TOKEN}"))
    bot.handle(tenant, USER, text="me cobraron doble")
    texts = [b for k, b in bot.sender.sent if k == "text"]
    assert HANDOFF_TOKEN not in " ".join(texts)
    assert bot.store.in_handoff(tenant.id, USER)


def test_tenants_are_isolated(bot, tenant):
    bot.handle(tenant, USER, text="hola")
    assert bot.store.history("otro-negocio", USER, 10) == []


def test_dedupe():
    s = Store(":memory:")
    assert s.mark_processed("wamid.1") and not s.mark_processed("wamid.1")


def test_helpers(tenant):
    assert normalize("  Menú!! ") == "menu"
    assert to_claude_messages([{"role": "assistant", "content": "x"},
                               {"role": "user", "content": "a"},
                               {"role": "user", "content": "b"}]) == [{"role": "user", "content": "a\nb"}]
    prompt = build_system_prompt(tenant)
    assert "Pizzería Don Mario" in prompt and "Hawaiana" in prompt


def test_signature():
    body, secret = b'{"x":1}', "s3cr3t"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(body, sig, secret)
    assert not verify_signature(body, "sha256=bad", secret)
