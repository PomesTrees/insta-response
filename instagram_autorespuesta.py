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
      IG_ACCESS_TOKEN.
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

6. DOS requisitos que no viven en el código y que, si faltan, hacen que Meta
   NUNCA entregue un webhook (aunque la suscripción aparezca activa y el botón
   "Test" del dashboard sí funcione — ese botón es un POST manual, no una
   entrega real):
   a. La app tiene que estar en modo **Live**, no Development. Meta lo dice
      explícito: "Apps must be set to Live in the App Dashboard to receive
      webhook notifications" y "Your app must be published, regardless of app
      review status, to receive webhooks". Es el switch Development/Live de la
      barra superior del App Dashboard; no hace falta pasar App Review.
   b. En la app de Instagram de la cuenta que recibe los DMs:
      Configuración → Mensajes y respuestas de historias → Controles de mensajes
      → Herramientas conectadas → "Permitir acceso a los mensajes" ACTIVADO.
      Con esto apagado, Meta ni manda webhooks ni expone nada en /conversations.

MANTENIMIENTO DEL TOKEN (lo único que rompe este bot con el tiempo)

El IG_ACCESS_TOKEN dura **60 días**. Cuando caduca, los webhooks siguen
llegando pero cada respuesta falla; el bot te avisa por Telegram con el error y
estas instrucciones, así que no te vas a enterar tarde. Para refrescarlo:

    cd insta_response
    set -a; source .env; set +a
    curl -s "https://graph.instagram.com/refresh_access_token\
?grant_type=ig_refresh_token&access_token=${IG_ACCESS_TOKEN}"

Devuelve un token nuevo y los segundos que le quedan:
    {"access_token":"IGAA...","token_type":"bearer","expires_in":5184000}

Pega ese access_token en DOS sitios, o el arreglo dura hasta el siguiente
deploy: el `.env` local y las Environment Variables del servicio en Render
(Render redespliega solo al guardar).

Dos condiciones de la API: el token tiene que tener más de 24 horas de vida y
menos de 60 días. Si ya caducó, refrescar no funciona y toca generar uno nuevo
desde el dashboard (API setup with Instagram Login → Generate Token). Lo más
sencillo es refrescarlo cada vez que te acuerdes; no hay penalización por
hacerlo pronto y cada refresco reinicia los 60 días.

Seguridad: este servidor verifica la firma X-Hub-Signature-256 que Meta manda en
cada webhook, usando tu App Secret (Dashboard → App settings → Basic → App Secret).
Esto evita que alguien que descubra tu URL pueda mandar payloads falsos y hacer
que el bot responda o notifique cosas que Meta nunca envió.

Instala dependencias:
    pip install flask requests
"""

import hashlib
import hmac
import json
import logging
import os
import random
import sys
import time

import requests
from dotenv import load_dotenv
from flask import Flask, request

load_dotenv()  # en local lee ".env"; en Render no hace nada (las env vars ya están seteadas)

# Log a stdout para que Render lo capture. Sin esto, un webhook rechazado por
# firma inválida se iba en silencio absoluto y parecía "no llegó nada".
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("insta-response")

app = Flask(__name__)

# --- Configuración (usa variables de entorno, nunca hardcodees tokens) ---
VERIFY_TOKEN = os.environ["IG_VERIFY_TOKEN"]        # lo inventas tú, lo pones también en el dashboard de Meta

# Tokens de las cuentas de Instagram conectadas, separados por comas. Cada cuenta
# tiene el suyo (API setup with Instagram Login → Generate Token, una vez por
# cuenta). Para una sola cuenta sirve igual IG_ACCESS_TOKEN, que se sigue
# leyendo por compatibilidad.
#
#   IG_ACCESS_TOKENS=IGAAxxx...,IGAAyyy...,IGAAzzz...
#
# No hace falta configurar los IDs de cada cuenta: al arrancar se consulta
# GET /me con cada token y se arma sola la tabla de enrutamiento. Así no hay
# forma de emparejar mal un token con un ID.
def _tokens_configurados() -> list[str]:
    crudo = os.environ.get("IG_ACCESS_TOKENS") or os.environ.get("IG_ACCESS_TOKEN", "")
    return [t.strip() for t in crudo.split(",") if t.strip()]

# App Secret para validar la firma de los webhooks.
# Meta documenta el de App settings → Basic → App Secret, pero "API setup with
# Instagram Login" expone además un "Instagram App Secret" distinto. Aceptamos
# los dos: si alguno valida, el payload es auténtico, y el log dice cuál fue.
APP_SECRETS = {
    nombre: valor
    for nombre, valor in (
        ("IG_APP_SECRET", os.environ.get("IG_APP_SECRET", "")),
        ("IG_APP_SECRET_ALT", os.environ.get("IG_APP_SECRET_ALT", "")),
    )
    if valor
}
if not APP_SECRETS:
    raise RuntimeError("Falta IG_APP_SECRET (o IG_APP_SECRET_ALT) en el entorno")

# IGSID (Instagram-Scoped ID) del usuario específico al que quieres responder distinto.
# Lo obtienes viendo el campo "sender.id" del primer webhook que te mande ese usuario.
USUARIO_ESPECIFICO_IGSID = os.environ.get("USUARIO_ESPECIFICO_IGSID", "")

# Notificaciones por Telegram (te avisan a ti, no al usuario de Instagram)
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Banco de respuestas. Se elige una al azar en cada mensaje entrante, para que
# la cuenta no conteste siempre exactamente lo mismo. Añade o quita frases aquí.
RESPUESTAS = ["HEYY", "wait", "give me 5", "yes"]
RESPUESTAS_USUARIO_ESPECIFICO = ["HEYYY"]

# Texto que Meta devuelve cuando el access token ya no sirve. Sirve para darte
# instrucciones concretas en el aviso de Telegram en vez de un error crudo.
TOKEN_CADUCADO = "Error validating access token"

# No repetir el mismo aviso de fallo más de una vez cada 15 min.
VENTANA_AVISO_REPETIDO_S = 15 * 60
_ultimos_avisos: dict[str, float] = {}


class Cuenta:
    """Una cuenta de Instagram conectada, con su token propio."""

    def __init__(self, token: str, id_: str, user_id: str, username: str):
        self.token = token
        self.id = id_
        self.user_id = user_id
        self.username = username

    def __repr__(self) -> str:  # solo para logs
        return f"@{self.username} (id={self.id}, user_id={self.user_id})"


# Tabla de enrutamiento: se indexa cada cuenta por sus DOS identificadores,
# porque según el evento Meta manda uno u otro y no siempre el mismo.
CUENTAS: dict[str, Cuenta] = {}


def cargar_cuentas() -> None:
    """Resuelve cada token a su cuenta con GET /me y llena CUENTAS.

    Un token inválido no tumba el arranque: se registra el error y las demás
    cuentas siguen funcionando. Si ninguna carga, el bot arranca igual y lo
    dice en el log — así el health check sigue vivo y puedes diagnosticarlo,
    en vez de tener un servicio que no levanta y no explica por qué."""
    for token in _tokens_configurados():
        try:
            r = requests.get(
                "https://graph.instagram.com/v21.0/me",
                params={"fields": "id,user_id,username", "access_token": token},
                timeout=10,
            )
        except requests.RequestException as e:
            log.error("No se pudo resolver un token contra la API: %s", e)
            continue

        if not r.ok:
            log.error("Token rechazado por Meta al arrancar: %s %s",
                      r.status_code, r.text[:300])
            continue

        datos = r.json()
        cuenta = Cuenta(token, datos.get("id", ""), datos.get("user_id", ""),
                        datos.get("username", "?"))
        for identificador in (cuenta.id, cuenta.user_id):
            if identificador:
                CUENTAS[identificador] = cuenta
        log.info("Cuenta cargada: %s", cuenta)

    if not CUENTAS:
        log.error("NINGUNA cuenta de Instagram cargada: revisa IG_ACCESS_TOKENS. "
                  "El bot recibirá webhooks pero no podrá responder.")
    else:
        log.info("%d cuenta(s) activa(s)", len({c.id for c in CUENTAS.values()}))


def cuenta_del_evento(entry: dict, evento: dict) -> Cuenta | None:
    """Averigua a qué cuenta conectada iba dirigido el mensaje.

    Meta identifica a la cuenta receptora en `entry.id`, y también en
    `messaging[].recipient.id`. Se prueban los dos porque el formato varía
    entre tipos de evento y no queremos depender de cuál manda hoy."""
    candidatos = [entry.get("id"), evento.get("recipient", {}).get("id")]
    for identificador in candidatos:
        if identificador and identificador in CUENTAS:
            return CUENTAS[identificador]

    # Con una sola cuenta configurada no hay ambigüedad posible: responde igual
    # aunque el ID no cuadre, en vez de quedarse callado por un detalle de formato.
    unicas = {c.id: c for c in CUENTAS.values()}
    if len(unicas) == 1:
        cuenta = next(iter(unicas.values()))
        log.warning("IDs del evento %s no están en la tabla; uso la única cuenta (%s)",
                    candidatos, cuenta)
        return cuenta

    log.error("No sé a qué cuenta pertenece el evento. IDs vistos: %s. "
              "Cuentas conocidas: %s", candidatos, sorted(CUENTAS))
    return None


cargar_cuentas()


@app.route("/", methods=["GET"])
def health_check():
    """Ping simple para monitoreo externo (ej. cron-job.org) y health checks de Render."""
    return "ok", 200


@app.route("/privacy", methods=["GET"])
def politica_privacidad():
    """Meta exige una Privacy Policy URL para poder pasar la app a modo Live.
    Se sirve desde aquí para no depender de otro hosting: la URL a pegar en
    App settings → Basic → Privacy policy URL es
    https://insta-response.onrender.com/privacy
    El texto describe lo que este archivo hace de verdad; si cambias el
    tratamiento de datos, actualízalo."""
    return POLITICA_PRIVACIDAD_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/webhook", methods=["GET"])
def verificar_webhook():
    """Meta llama a este endpoint una sola vez para validar la URL del webhook."""
    modo = request.args.get("hub.mode")
    token_recibido = request.args.get("hub.verify_token")

    if modo == "subscribe" and token_recibido == VERIFY_TOKEN:
        log.info("Verificación de webhook OK")
        return request.args.get("hub.challenge"), 200

    log.warning("Verificación de webhook RECHAZADA (mode=%s, token coincide=%s)",
                modo, token_recibido == VERIFY_TOKEN)
    return "Token de verificación inválido", 403


@app.route("/webhook", methods=["POST"])
def recibir_evento():
    """Meta manda aquí cada mensaje / solicitud de mensaje entrante en tiempo real."""
    cuerpo_crudo = request.get_data()
    firma_recibida = request.headers.get("X-Hub-Signature-256", "")

    # Primera línea siempre, pase lo que pase después: si esto no aparece en los
    # logs de Render, Meta realmente no está entregando el evento.
    log.info("POST /webhook recibido (%d bytes, firma presente=%s)",
             len(cuerpo_crudo), bool(firma_recibida))

    secret_usado = secret_que_valida(cuerpo_crudo, firma_recibida)
    if not secret_usado:
        # Alguien mandó un request que no viene realmente de Meta: lo rechazamos.
        log.warning("Firma inválida — rechazado. Body: %s", cuerpo_crudo[:500])
        return "Firma inválida", 403

    log.info("Firma válida (%s). Payload: %s", secret_usado, cuerpo_crudo[:1000])

    data = request.get_json(silent=True) or {}

    if data.get("object") != "instagram":
        log.info("Ignorado: object=%r, no es 'instagram'", data.get("object"))
        return "ok", 200

    for entry in data.get("entry", []):
        for evento in entry.get("messaging", []):
            try:
                procesar_evento(entry, evento)
            except Exception:
                # Un evento roto no debe tumbar el lote entero. Si devolviéramos
                # 500, Meta reintenta el batch COMPLETO y se repiten las
                # respuestas que sí habían salido bien.
                log.exception("Fallo procesando evento: %s",
                              json.dumps(evento)[:300])

    # Responde 200 rápido; si tardas demasiado, Meta reintenta el webhook.
    return "ok", 200


def procesar_evento(entry: dict, evento: dict) -> None:
    """Decide si un evento de messaging merece respuesta y la manda."""
    remitente_id = evento.get("sender", {}).get("id")
    mensaje = evento.get("message") or {}

    if not remitente_id:
        log.info("Evento sin sender.id, ignorado: %s", json.dumps(evento)[:300])
        return

    # Ignora el eco de tus propios mensajes salientes.
    if mensaje.get("is_echo"):
        log.info("Eco de mensaje propio, ignorado")
        return

    # Con varias cuentas conectadas, el remitente de un mensaje a la cuenta A
    # puede ser la cuenta B. Sin esto, dos cuentas tuyas se responderían entre
    # sí en bucle infinito.
    if remitente_id in CUENTAS:
        log.info("Remitente %s es una cuenta propia, ignorado (evita bucles)",
                 CUENTAS[remitente_id])
        return

    # Los eventos de lectura, entrega y reacciones también llegan por
    # entry[].messaging[] y NO traen contenido. Sin este filtro el bot
    # contestaba a los acuses de lectura de su propia respuesta.
    if not (mensaje.get("text") or mensaje.get("attachments")):
        log.info("Evento sin texto ni adjuntos (%s), ignorado",
                 ", ".join(k for k in evento if k != "sender") or "vacío")
        return

    cuenta = cuenta_del_evento(entry, evento)
    if cuenta is None:
        notificar_telegram_una_vez(
            "⚠️ Llegó un mensaje a una cuenta de Instagram que no tengo "
            "configurada. Revisa IG_ACCESS_TOKENS."
        )
        return

    log.info("Mensaje para @%s de %s: %r",
             cuenta.username, remitente_id, mensaje.get("text"))

    texto_respuesta = elegir_respuesta(remitente_id)
    error = enviar_mensaje(cuenta, remitente_id, texto_respuesta)

    if error is None:
        log.info("@%s respondió a %s", cuenta.username, remitente_id)
        notificar_telegram(
            f"✅ @{cuenta.username} respondió a {remitente_id} en Instagram:\n"
            f"«{texto_respuesta}»\n\n"
            f"Su mensaje: «{mensaje.get('text') or '(sin texto)'}»"
        )
        return

    # Avisar también cuando FALLA. Antes solo se notificaba el éxito, así que el
    # día que caduque el token el bot dejaría de responder en silencio y el error
    # solo quedaría en los logs de Render.
    log.error("@%s no pudo responder a %s: %s", cuenta.username, remitente_id, error)
    aviso = (f"⚠️ @{cuenta.username} NO pudo responder a {remitente_id} "
             f"en Instagram.\n\n{error}")
    if TOKEN_CADUCADO in error or "OAuth" in error:
        aviso += (
            f"\n\nParece que el token de @{cuenta.username} caducó o dejó de ser "
            "válido. Refréscalo (dura 60 días) y actualiza IG_ACCESS_TOKENS en "
            "Render:\ncurl -s 'https://graph.instagram.com/refresh_access_token"
            "?grant_type=ig_refresh_token&access_token=EL_TOKEN_DE_ESA_CUENTA'"
        )
    notificar_telegram_una_vez(aviso)


def secret_que_valida(cuerpo_crudo: bytes, firma_recibida: str) -> str | None:
    """Confirma que el request realmente viene de Meta, comparando la firma
    HMAC-SHA256 del header contra una calculada con cada App Secret conocido.
    Devuelve el nombre del secret que validó, o None si ninguno lo hizo."""
    if not firma_recibida.startswith("sha256="):
        return None

    firma_recibida = firma_recibida.removeprefix("sha256=")
    for nombre, secret in APP_SECRETS.items():
        firma_esperada = hmac.new(
            secret.encode("utf-8"), cuerpo_crudo, hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(firma_esperada, firma_recibida):
            return nombre
    return None


def elegir_respuesta(remitente_id: str) -> str:
    """Saca una frase al azar del banco que corresponda al remitente."""
    if USUARIO_ESPECIFICO_IGSID and remitente_id == USUARIO_ESPECIFICO_IGSID:
        return random.choice(RESPUESTAS_USUARIO_ESPECIFICO)
    return random.choice(RESPUESTAS)


def enviar_mensaje(cuenta: "Cuenta", destinatario_id: str, texto: str) -> str | None:
    """Envía la respuesta desde la cuenta indicada.
    Devuelve None si Meta la aceptó, o el motivo del fallo si no.

    El path usa "me", que con la API de Instagram Login resuelve a la cuenta
    dueña del token. Así cada cuenta se identifica sola por su token y no hay
    forma de mandar un mensaje desde la cuenta equivocada."""
    url = "https://graph.instagram.com/v21.0/me/messages"
    payload = {
        "recipient": {"id": destinatario_id},
        "message": {"text": texto},
        "messaging_type": "RESPONSE",
    }
    headers = {"Authorization": f"Bearer {cuenta.token}"}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
    except requests.RequestException as e:
        return f"No se pudo contactar a la API de Instagram: {e}"

    if not r.ok:
        return f"HTTP {r.status_code} de la API de Instagram: {r.text[:400]}"
    return None


def notificar_telegram(texto: str) -> None:
    """Te manda un mensaje a ti (no al usuario de Instagram) avisando lo que pasó."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": texto}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            log.error("Error notificando por Telegram: %s %s", r.status_code, r.text)
    except requests.RequestException as e:
        # Que un fallo de Telegram nunca tumbe el flujo principal del bot
        log.error("Excepción notificando por Telegram: %s", e)


def notificar_telegram_una_vez(texto: str) -> None:
    """Como notificar_telegram, pero no repite el mismo aviso durante un rato.

    Si el token caduca, TODOS los mensajes que entren van a fallar igual; sin
    esto recibirías una alerta idéntica por cada DM. La ventana se lleva por
    texto, así que un error distinto sí avisa de inmediato.

    Nota: gunicorn corre con varios workers y cada uno tiene su propio dict, así
    que en la práctica puedes recibir hasta una alerta por worker. Es aceptable:
    el objetivo es no inundar, no garantizar exactly-once."""
    ahora = time.monotonic()
    ultimo_envio = _ultimos_avisos.get(texto, 0.0)
    if ahora - ultimo_envio < VENTANA_AVISO_REPETIDO_S:
        log.info("Aviso repetido, silenciado durante la ventana")
        return

    _ultimos_avisos[texto] = ahora
    # Evita que el dict crezca sin límite si aparecen muchos errores distintos.
    for viejo, t in list(_ultimos_avisos.items()):
        if ahora - t > VENTANA_AVISO_REPETIDO_S:
            del _ultimos_avisos[viejo]

    notificar_telegram(texto)


POLITICA_PRIVACIDAD_HTML = """<!doctype html>
<html lang="es">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Política de privacidad — Auto-respuesta de @occhakitten</title>
<style>
  body { max-width: 42rem; margin: 3rem auto; padding: 0 1.25rem;
         font: 16px/1.6 system-ui, -apple-system, sans-serif; color: #1a1a1a; }
  h1 { font-size: 1.5rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
  code { background: #f2f2f2; padding: .1em .3em; border-radius: 3px; }
  footer { margin-top: 3rem; color: #666; font-size: .875rem; }
  @media (prefers-color-scheme: dark) {
    body { background: #161616; color: #e8e8e8; }
    code { background: #2a2a2a; } footer { color: #999; }
  }
</style>
<h1>Política de privacidad</h1>
<p>Esta política cubre el bot de respuesta automática de mensajes directos de la
cuenta de Instagram <strong>@occhakitten</strong>. Es un proyecto personal, sin
fines comerciales, operado por el titular de esa cuenta.</p>

<h2>Qué datos se tratan</h2>
<p>Cuando envías un mensaje directo a @occhakitten, Meta notifica a este servidor
con dos datos: tu <em>identificador de usuario con alcance de Instagram</em>
(IGSID, un número que solo identifica tu cuenta frente a esta aplicación y no
revela tu perfil) y el contenido del mensaje que enviaste.</p>
<p>No se solicita, ni se recoge, ningún otro dato: ni correo, ni teléfono, ni
ubicación, ni datos de pago.</p>

<h2>Para qué se usan</h2>
<p>Exclusivamente para dos cosas: enviarte una respuesta automática por Instagram
y avisar al titular de la cuenta, mediante una notificación privada de Telegram,
de que hubo un mensaje nuevo.</p>

<h2>Cuánto tiempo se conservan</h2>
<p>No hay base de datos: los mensajes no se guardan ni se usan para crear
perfiles. Los eventos recibidos sí quedan registrados de forma temporal en los
registros técnicos del servidor (alojado en Render), que se conservan solo unos
días y se borran de forma automática.</p>

<h2>Con quién se comparten</h2>
<p>Con nadie. Los datos no se venden, alquilan ni ceden. Solo pasan por los
proveedores estrictamente necesarios para que el servicio funcione: Meta
(Instagram), que origina el mensaje; Render, que aloja el servidor; y Telegram,
que entrega el aviso privado al titular.</p>

<h2>Tus derechos</h2>
<p>Puedes pedir en cualquier momento que se consulte o elimine cualquier dato
relacionado contigo, o dejar de usar el servicio simplemente no escribiendo a la
cuenta. Para ejercer estos derechos, escribe a
<code>occhakitten@gmail.com</code>.</p>

<h2>Cambios</h2>
<p>Si cambia el tratamiento de datos, esta página se actualiza con una nueva
fecha de revisión.</p>

<footer>Última actualización: 6 de agosto de 2026 &middot;
Contacto: occhakitten@gmail.com</footer>
</html>
"""


if __name__ == "__main__":
    # NUNCA uses debug=True si este servidor va a estar expuesto a internet:
    # el debugger interactivo de Werkzeug permite ejecutar código arbitrario
    # a quien lo alcance. Para producción real, usa un servidor WSGI como
    # gunicorn en vez de app.run() (ej. gunicorn -w 2 -b 0.0.0.0:5000 archivo:app).
    app.run(port=5000, debug=False)
