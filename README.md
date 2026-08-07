# insta-response — versión Render

Bot que responde automáticamente los mensajes directos de Instagram, al
instante, y te avisa por Telegram cada vez que lo hace.

Está pensado para cuentas profesionales que reciben más DMs de los que se
pueden contestar a tiempo: el bot manda una respuesta breve en cuanto llega el
mensaje, para que la persona sepa que la leíste, y te notifica a ti para que
respondas de verdad cuando puedas.

> **Esta rama despliega en [Render](https://render.com) con su plan gratuito.**
> Es la forma más rápida de ponerlo en marcha: no hay servidor que administrar,
> ni certificados, ni cortafuegos. Subes el código y funciona.
>
> Si prefieres alojarlo en un servidor propio con Docker, mira la rama
> [`oracle`](../../tree/oracle). La comparación está más abajo.

---

## Qué hace, en orden

1. Alguien te escribe un DM en Instagram.
2. Meta avisa a este servidor al instante.
3. El bot comprueba que el aviso viene de Meta de verdad y no de un impostor.
4. Contesta con una frase al azar de tu lista (`"HEYY"`, `"wait"`, `"give me 5"`…).
5. Te manda un Telegram diciéndote quién escribió, qué dijo y qué se le contestó.

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
- Una cuenta gratuita en Render.

**Aviso importante:** la app de Meta tiene que estar en modo **Live**, no en
Development. En Development, Meta acepta la configuración, muestra la
suscripción como activa y el botón de prueba funciona… pero **no entrega ni un
solo mensaje real**. Es el fallo más desconcertante de montar esto, porque nada
da error. Pasar a Live es un interruptor en el panel de la app y no requiere
pasar App Review.

---

## Desplegar en Render

1. Crea un **Web Service** apuntando a este repositorio, rama `main`.
2. Render detecta el `Procfile` solo; no hay que configurar el comando de
   arranque.
3. En **Environment**, añade las variables de la tabla de abajo.
4. Cuando el servicio esté *Live*, apunta Meta a él:
   - **Callback URL:** `https://TU-SERVICIO.onrender.com/webhook`
   - **Verify Token:** el mismo `IG_VERIFY_TOKEN` que pusiste en Render
5. En **App settings → Basic → Privacy policy URL**, pon
   `https://TU-SERVICIO.onrender.com/privacy`. Meta la exige para publicar la app,
   y el propio bot la sirve.

Cada `git push` a `main` redespliega automáticamente.

---

## Configuración

En local, copia `.env.example` a `.env` y rellénalo. **Ese archivo nunca se sube
a git.** En Render, los mismos valores van en *Environment Variables*.

| Variable | Qué es |
|---|---|
| `IG_ACCESS_TOKENS` | Los tokens de tus cuentas de Instagram, separados por comas |
| `IG_VERIFY_TOKEN` | Una contraseña que inventas tú; va también en el panel de Meta |
| `IG_APP_SECRET` | Sirve para comprobar que los mensajes vienen de Meta |
| `TELEGRAM_BOT_TOKEN` | El token que te da BotFather |
| `TELEGRAM_CHAT_ID` | Tu chat de Telegram, para saber a quién avisar |
| `USUARIO_ESPECIFICO_IGSID` | Opcional: una persona que recibe respuesta distinta |

### Cambiar las respuestas

Están al principio de `instagram_autorespuesta.py`:

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

Al arrancar, el bot le pregunta a Instagram a qué cuenta pertenece cada token y
arma solo el enrutado. Cada mensaje se responde desde la cuenta a la que llegó.

---

## Las dos limitaciones del plan gratuito de Render

Conviene conocerlas antes de decidir, porque no son evidentes:

**Se duerme.** Render suspende el servicio tras **15 minutos sin tráfico**.
El primer mensaje que llegue después despierta la máquina, y eso tarda entre 20
y 60 segundos. Meta reintenta la entrega, así que el mensaje no se pierde, pero
la respuesta "instantánea" deja de serlo.

Se puede evitar con un ping externo gratuito (cron-job.org, UptimeRobot) cada
10 minutos, aunque eso lleva a la segunda limitación.

**Tiene cuota mensual.** El plan gratuito da **750 horas de instancia al mes**
por cuenta. Un mes de 31 días tiene 744 horas, así que mantener el servicio
despierto todo el mes consume el 99 % de la cuota. Cabe justo, pero solo si es
el único servicio gratuito de tu cuenta.

---

## ¿Esta rama o la de `oracle`?

| | `main` (Render) | [`oracle`](../../tree/oracle) (servidor propio) |
|---|---|---|
| Puesta en marcha | Minutos | Unas horas |
| Administración | Ninguna | Tuya |
| Se duerme | Sí, a los 15 min | No |
| Cuota mensual | 750 horas | Sin límite |
| Certificados HTTPS | Los pone Render | Automáticos con Caddy |
| Alojar más proyectos | Un servicio más | Contenedores en la misma máquina |

**Empieza por `main`.** Si el bot te resulta útil y las esperas del arranque en
frío te molestan, o quieres alojar más cosas en el mismo sitio, la rama `oracle`
tiene la guía completa para montarlo en un servidor propio.

El código de la aplicación es el mismo en las dos ramas. Solo cambia cómo se
despliega.

---

## Uso diario

Los registros están en el panel de Render, en la pestaña **Logs**. Ahí se ve
cada mensaje que entra, si la firma se validó y qué se respondió.

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

Pega el token nuevo en las variables de entorno de Render y guarda; el servicio
se redespliega solo. Cada renovación reinicia los 60 días y puedes hacerla
cuando quieras, sin penalización por adelantarse.

Si se te pasa la fecha, el bot te avisará por Telegram en cuanto llegue el
primer mensaje que no pueda contestar.

---

## Sobre la privacidad

El bot recibe el identificador del remitente y el texto del mensaje, los usa
para responder y avisarte, y no los guarda en ninguna base de datos. Sirve su
propia política de privacidad en `/privacy`, que es la que se registra en el
panel de Meta.

---

## Notas

Proyecto personal, sin fines comerciales. El código está comentado en
castellano y explica **por qué** hace cada cosa, no solo qué hace: buena parte
de esas notas son cicatrices de problemas reales que costaron horas encontrar.
Si vas a modificarlo, léelas antes de simplificar algo que parezca innecesario.
