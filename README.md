# insta-response

Bot que responde automáticamente los mensajes directos de Instagram, al
instante, y te avisa por Telegram cada vez que lo hace.

Está pensado para cuentas profesionales que reciben más DMs de los que se
pueden contestar a tiempo: el bot manda una respuesta breve en cuanto llega el
mensaje, para que la persona sepa que la leíste, y te notifica a ti para que
respondas de verdad cuando puedas.

---

## Qué hace, en orden

1. Alguien te escribe un DM en Instagram.
2. Meta avisa a este servidor al instante.
3. El bot comprueba que el aviso viene de Meta de verdad y no de un impostor.
4. Contesta con una frase al azar de tu lista (`"HEYY"`, `"wait"`, `"give me 5"`…).
5. Te manda un Telegram diciéndote quién escribió, qué dijo y qué se le contestó.

Tarda alrededor de **un segundo** desde que entra el mensaje hasta que sale la
respuesta.

```
Instagram ──► Meta ──► este bot ──┬──► responde en Instagram
                                  └──► te avisa por Telegram
```

---

## Qué necesitas

- Una cuenta de Instagram **profesional** (Business o Creator).
- Una app en [Meta for Developers](https://developers.facebook.com) con el caso
  de uso *"Manage messaging & content on Instagram"*.
- Un bot de Telegram, creado con [@BotFather](https://t.me/BotFather).
- Un servidor con HTTPS y certificado válido. Meta no entrega mensajes a
  direcciones sin cifrar ni con certificados autofirmados.

**Aviso importante:** la app de Meta tiene que estar en modo **Live**, no en
Development. En Development, Meta acepta la configuración, muestra la
suscripción como activa y el botón de prueba funciona… pero **no entrega ni un
solo mensaje real**. Es el fallo más desconcertante de montar esto, porque nada
da error. Pasar a Live es un interruptor en el panel de la app y no requiere
pasar App Review.

---

## Configuración

Todos los valores van en un archivo `.env` (copia `.env.example` y rellénalo).
**Ese archivo nunca se sube a git.**

| Variable | Qué es |
|---|---|
| `IG_ACCESS_TOKENS` | Los tokens de tus cuentas de Instagram, separados por comas |
| `IG_VERIFY_TOKEN` | Una contraseña que inventas tú; va también en el panel de Meta |
| `IG_APP_SECRET` | Sirve para comprobar que los mensajes vienen de Meta |
| `TELEGRAM_BOT_TOKEN` | El token que te da BotFather |
| `TELEGRAM_CHAT_ID` | Tu chat de Telegram, para saber a quién avisar |
| `USUARIO_ESPECIFICO_IGSID` | Opcional: una persona que recibe respuesta distinta |

### Cambiar las respuestas

Están al principio de `instagram_autorespuesta.py`. Añade o quita frases:

```python
RESPUESTAS = ["HEYY", "wait", "give me 5", "yes"]
```

Se elige una al azar en cada mensaje, para que la cuenta no conteste siempre lo
mismo.

### Usar varias cuentas de Instagram

Pon los tokens separados por comas y ya está:

```
IG_ACCESS_TOKENS=IGAAxxx...,IGAAyyy...
```

No hace falta configurar nada más. Al arrancar, el bot le pregunta a Instagram a
qué cuenta pertenece cada token y arma solo el enrutado. Cada mensaje se
responde desde la cuenta a la que llegó.

---

## Ponerlo en marcha

```bash
docker network create web             # solo la primera vez
cd ~/infra && docker compose up -d    # el proxy compartido, fuera de este repo
cd ~/insta-response && docker compose up -d --build
```

El reverse proxy que termina TLS **no vive aquí**: es compartido por todos los
sitios del servidor y está en `~/infra`, con su propio README. Este repositorio
solo contiene el bot, que no publica ningún puerto y solo es alcanzable a
través de ese proxy.

Y en el panel de Meta, en la sección Webhooks del objeto Instagram:

- **Callback URL:** `https://TU-DOMINIO/webhook`
- **Verify Token:** el mismo `IG_VERIFY_TOKEN` de tu `.env`

La guía completa, paso a paso y con los tropiezos típicos, está en
[`DESPLIEGUE-ORACLE.md`](DESPLIEGUE-ORACLE.md).

---

## Uso diario

```bash
docker compose logs -f bot     # ver qué está pasando
docker compose restart bot     # reiniciar
docker compose up -d --build   # aplicar cambios del código
```

Si algo falla al responder, **te enteras por Telegram**, no revisando logs. El
aviso incluye el error y, cuando es por el token caducado, las instrucciones
para renovarlo.

---

## Mantenimiento

Solo hay una cosa que caduca: el **token de acceso de Instagram**, que dura
**60 días**. Para renovarlo:

```bash
curl -s "https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=TU_TOKEN_ACTUAL"
```

Pega el token nuevo en el `.env` y reinicia con `docker compose up -d`. Cada
renovación reinicia los 60 días y puedes hacerla cuando quieras; no hay
penalización por adelantarse.

Si se te pasa la fecha, el bot te avisará por Telegram en cuanto llegue el
primer mensaje que no pueda contestar.

---

## Sobre la privacidad

El bot recibe el identificador del remitente y el texto del mensaje, los usa
para responder y avisarte, y no los guarda en ninguna base de datos. Sirve su
propia política de privacidad en `/privacy`, que es la que se registra en el
panel de Meta.

---

## Documentación

| Documento | Para qué |
|---|---|
| Este README | Qué hace y cómo configurarlo |
| [`DESPLIEGUE-ORACLE.md`](DESPLIEGUE-ORACLE.md) | Desplegarlo en un servidor propio, paso a paso |
| Comentarios del código | El porqué de cada decisión, junto al código que la aplica |

---

## Notas

Proyecto personal, sin fines comerciales. El código está comentado en
castellano y explica **por qué** hace cada cosa, no solo qué hace: buena parte
de esas notas son cicatrices de problemas reales que costaron horas encontrar.
Si vas a modificarlo, léelas antes de simplificar algo que parezca innecesario.
