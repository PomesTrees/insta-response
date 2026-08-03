"""
Bot de auto-respuesta para Instagram Direct usando la Instagram Messaging API
(Graph API oficial de Meta).

Requisitos previos:
1. Cuenta de Instagram profesional (Business o Creator).
2. App de Meta creada en developers.facebook.com con el use case
   "Manage messaging & content on Instagram" → API setup with Instagram Login:
   a. Add account: conecta tu cuenta de Instagram directamente (login de Instagram,
      no de Facebook).
   b. Add all required permissions (agrega instagram_business_basic e
      instagram_business_manage_messages).
   c. Generate Token: te da un token de larga duración (60 días). Ese es tu
      IG_ACCESS_TOKEN. El "Instagram User ID" que se muestra ahí es tu IG_ACCOUNT_ID.
3. Webhooks configurados en el dashboard: objeto Instagram, Callback URL
   apuntando a /webhook de este servidor, mismo IG_VERIFY_TOKEN de abajo,
   suscrito al campo "messages".
4. Servidor HTTPS público (ngrok en desarrollo, Render/Railway/VPS en producción)
   para recibir los webhooks.
5. Un bot de Telegram para recibir la notificación de "mensaje respondido":
   a. En Telegram, busca @BotFather y envía /newbot. Sigue los pasos y guarda
      el token que te da (algo como 123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx).
   b. Abre un chat con tu bot recién creado y mándale cualquier mensaje
      (ej. "hola") para iniciar la conversación.
   c. Visita en el navegador:
      https://api.telegram.org/bot<TU_TOKEN>/getUpdates
      y busca el campo "chat":{"id": ...} — ese número es tu TELEGRAM_CHAT_ID.

Nota sobre el token: dura 60 días. Antes de que expire, refréscalo con un GET a
https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=TU_TOKEN

Seguridad: este servidor verifica la firma X-Hub-Signature-256 que Meta manda en
cada webhook, usando tu App Secret (Dashboard → App settings → Basic → App Secret).
Esto evita que alguien que descubra tu URL pueda mandar payloads falsos y hacer
que el bot responda o notifique cosas que Meta nunca envió.

Instala dependencias:
    pip install flask requests
"""

import hmac
import hashlib
import os
import requests
from dotenv import load_dotenv
from flask import Flask, request

load_dotenv()  # en local lee ".env"; en Render no hace nada (las env vars ya están seteadas)

app = Flask(__name__)

# --- Configuración (usa variables de entorno, nunca hardcodees tokens) ---
VERIFY_TOKEN = os.environ["IG_VERIFY_TOKEN"]        # lo inventas tú, lo pones también en el dashboard de Meta
IG_ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]      # token generado en API setup with Instagram Login
IG_ACCOUNT_ID = os.environ["IG_ACCOUNT_ID"]          # tu Instagram User ID (se muestra en esa misma pantalla)
APP_SECRET = os.environ["IG_APP_SECRET"]             # App settings → Basic → App Secret (para verificar firmas)

# IGSID (Instagram-Scoped ID) del usuario específico al que quieres responder distinto.
# Lo obtienes viendo el campo "sender.id" del primer webhook que te mande ese usuario.
USUARIO_ESPECIFICO_IGSID = os.environ.get("USUARIO_ESPECIFICO_IGSID", "")

# Notificaciones por Telegram (te avisan a ti, no al usuario de Instagram)
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MENSAJE_GENERICO = "HEYY"
MENSAJE_USUARIO_ESPECIFICO = "HEYYY"


@app.route("/", methods=["GET"])
def health_check():
    """Ping simple para monitoreo externo (ej. UptimeRobot) y health checks de Render."""
    return "ok", 200


@app.route("/webhook", methods=["GET"])
def verificar_webhook():
    """Meta llama a este endpoint una sola vez para validar la URL del webhook."""
    if (
        request.args.get("hub.mode") == "subscribe"
        and request.args.get("hub.verify_token") == VERIFY_TOKEN
    ):
        return request.args.get("hub.challenge"), 200
    return "Token de verificación inválido", 403


@app.route("/webhook", methods=["POST"])
def recibir_evento():
    """Meta manda aquí cada mensaje / solicitud de mensaje entrante en tiempo real."""
    cuerpo_crudo = request.get_data()
    firma_recibida = request.headers.get("X-Hub-Signature-256", "")

    if not firma_valida(cuerpo_crudo, firma_recibida):
        # Alguien mandó un request que no viene realmente de Meta: lo rechazamos.
        return "Firma inválida", 403

    data = request.get_json(silent=True) or {}

    if data.get("object") != "instagram":
        return "ok", 200

    for entry in data.get("entry", []):
        for evento in entry.get("messaging", []):
            remitente_id = evento.get("sender", {}).get("id")
            mensaje = evento.get("message", {})

            # Ignora el eco de tus propios mensajes salientes y eventos sin texto
            if not remitente_id or mensaje.get("is_echo"):
                continue

            texto_respuesta = elegir_respuesta(remitente_id)
            enviado = enviar_mensaje(remitente_id, texto_respuesta)

            if enviado:
                notificar_telegram(
                    f"✅ Respondí a {remitente_id} en Instagram:\n"
                    f"«{texto_respuesta}»"
                )

    # Responde 200 rápido; si tardas demasiado, Meta reintenta el webhook.
    return "ok", 200


def firma_valida(cuerpo_crudo: bytes, firma_recibida: str) -> bool:
    """Confirma que el request realmente viene de Meta, comparando la firma
    HMAC-SHA256 que manda en el header contra una calculada con tu App Secret."""
    if not firma_recibida.startswith("sha256="):
        return False
    firma_esperada = hmac.new(
        APP_SECRET.encode("utf-8"), cuerpo_crudo, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(firma_esperada, firma_recibida.removeprefix("sha256="))


def elegir_respuesta(remitente_id: str) -> str:
    if USUARIO_ESPECIFICO_IGSID and remitente_id == USUARIO_ESPECIFICO_IGSID:
        return MENSAJE_USUARIO_ESPECIFICO
    return MENSAJE_GENERICO


def enviar_mensaje(destinatario_id: str, texto: str) -> bool:
    """Envía la respuesta al usuario de Instagram. Devuelve True si Meta la aceptó."""
    url = f"https://graph.instagram.com/v21.0/{IG_ACCOUNT_ID}/messages"
    payload = {
        "recipient": {"id": destinatario_id},
        "message": {"text": texto},
        "messaging_type": "RESPONSE",
    }
    headers = {"Authorization": f"Bearer {IG_ACCESS_TOKEN}"}
    r = requests.post(url, json=payload, headers=headers, timeout=10)
    if not r.ok:
        print("Error enviando mensaje:", r.status_code, r.text)
        return False
    return True


def notificar_telegram(texto: str) -> None:
    """Te manda un mensaje a ti (no al usuario de Instagram) avisando lo que pasó."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": texto}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print("Error notificando por Telegram:", r.status_code, r.text)
    except requests.RequestException as e:
        # Que un fallo de Telegram nunca tumbe el flujo principal del bot
        print("Excepción notificando por Telegram:", e)


if __name__ == "__main__":
    # NUNCA uses debug=True si este servidor va a estar expuesto a internet:
    # el debugger interactivo de Werkzeug permite ejecutar código arbitrario
    # a quien lo alcance. Para producción real, usa un servidor WSGI como
    # gunicorn en vez de app.run() (ej. gunicorn -w 2 -b 0.0.0.0:5000 archivo:app).
    app.run(port=5000, debug=False)
