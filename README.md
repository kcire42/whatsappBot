# WhatsApp Bot multi-negocio (FastAPI + WhatsApp Cloud API + Claude)

Un solo servidor atiende a **muchos negocios**. Cada cliente = un archivo YAML en `tenants/`.

## Cómo funciona (modo híbrido)
| Mensaje del cliente final | Qué pasa | Costo IA |
|---|---|---|
| "hola", "menú" | Menú interactivo (catálogo, pedido, horario, ubicación, pagos, humano) | 0 |
| Toca una opción del menú | Respuesta fija desde el YAML | 0 |
| "quiero un asesor" / la IA detecta que hace falta | Modo humano: el bot calla N horas | 0 |
| Pregunta abierta ("¿tienen vegetariana?") | Claude responde SOLO con datos del negocio | sí |

## Arranque local
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # completa los valores
set -a && source .env && set +a
uvicorn app.main:app --reload --port 8000
pytest -q                     # pruebas sin Meta ni Claude
```
Para que Meta alcance tu PC usa un túnel (ngrok / cloudflared) y registra `https://TU-URL/webhook`.

## Configurar Meta (una vez)
1. developers.facebook.com → Crear app (tipo *Business*) → producto **WhatsApp**.
2. Webhook: URL `https://TU-DOMINIO/webhook`, token de verificación = `WA_VERIFY_TOKEN`; suscribe el campo **messages**.
3. Copia el **App Secret** a `WA_APP_SECRET` (valida la firma de cada webhook).

## Dar de alta un cliente nuevo
1. Registra su número en tu cuenta de WhatsApp Business (o vía Embedded Signup).
2. Copia `tenants/pizzeria-demo.yaml` → `tenants/<cliente>.yaml` y cambia datos, `phone_number_id` y `token_env`.
3. Agrega el token permanente (usuario del sistema) en `.env` con ese nombre y reinicia.

## Estructura
```
app/main.py       webhook (verificación, firma, dedupe, procesa en segundo plano)
app/engine.py     motor híbrido: menús → humano → IA
app/ai.py         prompt por negocio + Claude (cache, fallback ante rechazos)
app/whatsapp.py   envío de texto y listas interactivas
app/store.py      SQLite: historial, dedupe, modo humano (aislado por negocio)
app/tenants.py    carga de negocios desde YAML
```
