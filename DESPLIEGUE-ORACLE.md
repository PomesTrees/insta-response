# Despliegue en el servidor de Oracle

El bot pasa de Render (plan free, se duerme y tiene cuota mensual) a un
contenedor en la VM de Oracle Cloud, que está siempre encendida.

Arquitectura: dos contenedores. `bot` corre la app Flask y **no** se expone a
internet; `caddy` es el reverse proxy que termina TLS y le pasa las peticiones
por la red interna de Docker. Meta exige HTTPS con certificado válido para
entregar webhooks, y Caddy lo pide y renueva solo contra Let's Encrypt.

```
Meta ──HTTPS──► caddy :443 ──HTTP──► bot :8000
                (Let's Encrypt)      (sin puerto publicado)
```

---

## Qué VM elegir si vas a alojar más proyectos

**Recomendación: Ampere A1 (ARM) con Ubuntu 24.04 LTS.**

El Always Free de Oracle incluye hasta **4 OCPU y 24 GB de RAM** en Ampere A1,
frente a **1 GB** de las micro x86. Para meter varios proyectos en contenedores
no hay comparación posible.

### La cuota de A1 da para una sola instancia llena

Oracle no regala "una instancia", regala **3.000 OCPU-horas y 18.000 GB-horas al
mes por tenancy**. Echando cuentas para 4 OCPU y 24 GB encendidos todo el mes:

| Mes | OCPU-horas | GB-horas | Margen |
|---|---|---|---|
| 30 días | 2.880 / 3.000 | 17.280 / 18.000 | 4 % |
| 31 días | 2.976 / 3.000 | 17.856 / 18.000 | **0,8 %** |

Cabe, pero justo. La cuota está dimensionada para exactamente una instancia de
4 OCPU / 24 GB a tiempo completo. **No crees una segunda instancia A1 ni amplíes
la forma**, o te sales del gratis. Si algún día necesitas separar proyectos,
hazlo con más contenedores en la misma VM, no con más VMs.

Ubuntu LTS sobre Oracle Linux por una razón práctica: casi toda la
documentación de Docker y las guías de terceros asumen Debian/Ubuntu, así que
cuando algo falle a las 2 de la mañana encontrarás la respuesta antes.

### Antes de meter una imagen nueva: comprueba que tiene arm64

Una VM ARM no ejecuta imágenes publicadas solo para amd64. Todo lo que usa este
proyecto sí las tiene (`python:3.12-slim`, `caddy`, `postgres`), pero para
cualquier imagen futura conviene mirarlo antes de montar el proyecto entero:

```bash
docker manifest inspect LA_IMAGEN:TAG | grep -o '"architecture": "[a-z0-9]*"' | sort -u
```

Si no aparece `arm64`, esa imagen solo correrá emulada con QEMU (lento) o
tendrá que ir a otra máquina. Suele pasar con software antiguo o sin
mantenimiento activo.

### Aviso serio: Oracle reclama instancias inactivas

En cuentas **Always Free**, una instancia cuyo percentil 95 de CPU se mantenga
**por debajo del 20 % durante 7 días** puede ser reclamada por Oracle. Fuente:
[Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Un bot que solo contesta DMs consume prácticamente nada, así que este servidor
entra de lleno en ese perfil. La ironía es evidente: se abandona Render porque
duerme el servicio, y Oracle puede llegar a borrar la instancia entera.

Tres formas de convivir con ello, de menos a más definitiva:

1. **Que el redespliegue sea trivial.** Ya lo es: todo está en git y se levanta
   con un `docker compose up -d --build`. Lo único que no está en el repo es el
   `.env`; guarda una copia segura fuera de la VM y recuperarse de una
   reclamación son minutos, no una tarde.
2. **Meter ahí otros proyectos reales** cuando los tengas. Sube el uso de CPU
   por motivos legítimos y de paso aprovecha los 24 GB.
3. **Pasar la cuenta a Pay As You Go.** Los recursos Always Free se siguen
   facturando a 0 € mientras no te salgas de sus límites, y las cuentas PAYG no
   están sujetas a la reclamación por inactividad. El coste es que añades un
   método de pago y asumes el riesgo de que un descuido fuera de los límites
   gratuitos sí genere factura. Verifica las condiciones vigentes antes de
   hacerlo: esto cambia con el tiempo y conviene leerlo en la consola de Oracle,
   no fiarse de una guía.

Ninguna de las tres es gratis del todo en esfuerzo o riesgo. La 1 ya la tienes
hecha y probablemente sea suficiente para un proyecto personal.

---

## Requisito previo: un nombre de dominio (gratis con DuckDNS)

Let's Encrypt no emite certificados para direcciones IP, y Meta exige HTTPS con
certificado válido. Sin dominio propio, **DuckDNS** da un subdominio gratuito
que sirve perfectamente.

1. Entra en <https://www.duckdns.org> y accede con GitHub/Google.
2. Crea un subdominio, por ejemplo `auto-response` → te queda
   `auto-response.duckdns.org`.
3. En el campo `current ip` pon la **IP pública de la VM** y pulsa *update ip*.
4. Copia tu **token** de DuckDNS (arriba en la misma página); hace falta para
   el actualizador automático del paso siguiente.

Comprueba que resuelve antes de seguir. Si Caddy pide el certificado con el DNS
todavía sin propagar, Let's Encrypt aplica límites de reintentos y tendrás que
esperar:

```bash
dig +short auto-response.duckdns.org
```

No hace falta tocar el `Caddyfile`: el desafío HTTP-01 de Let's Encrypt funciona
igual con un dominio de DuckDNS que con uno propio, siempre que el puerto 80
esté abierto (paso 1).

### Que la IP no se quede obsoleta

La IP pública que Oracle asigna por defecto es **efímera**: si paras y arrancas
la instancia, cambia, y el subdominio apuntaría al vacío. Dos arreglos, y
conviene hacer los dos:

**a) Reservar la IP** (recomendado, y entra en el Free Tier). En la consola:
Compute → Instances → tu instancia → Attached VNICs → la VNIC → IPv4 Addresses
→ edita la IP pública y cámbiala de *Ephemeral* a *Reserved*.

**b) Actualizador automático**, como red de seguridad. En la VM:

```bash
# sustituye SUBDOMINIO y TOKEN por los tuyos
(crontab -l 2>/dev/null; echo '*/15 * * * * curl -fsS "https://www.duckdns.org/update?domains=SUBDOMINIO&token=TOKEN&ip=" >/dev/null') | crontab -
```

Dejando `ip=` vacío, DuckDNS usa la IP desde la que llega la petición, así que
se corrige solo. El token es un secreto: no lo subas a git.

---

## 0. Actualizar Ubuntu 20.04 (obligatorio, no opcional)

Si la VM se creó con **Canonical Ubuntu 20.04**, hay que subirla de versión
antes de nada, por dos motivos:

1. **Docker ya no la soporta.** Las versiones que Docker Engine lista hoy son
   22.04, 24.04, 25.10 y 26.04. Focal no aparece: su repositorio no tiene
   paquetes para esa versión.
2. **Perdió el soporte estándar el 31 de mayo de 2025**, así que lleva más de un
   año sin parches de seguridad — en una máquina que vas a exponer con los
   puertos 80 y 443 abiertos.

### ⚠️ NO destruyas la instancia para recrearla con 24.04

Es la reacción natural y es un error caro. La capacidad de **Ampere A1 está muy
solicitada**: es habitual toparse con *"Out of capacity for shape
VM.Standard.A1.Flex"* durante días o semanas. Si terminas una instancia de 4
OCPU / 24 GB que ya funciona, puedes quedarte sin poder recrearla.

La actualización **in situ** conserva la instancia y no toca la capacidad.

### Actualización in situ

Es el mejor momento para hacerlo: todavía no hay nada desplegado, así que no
hay servicios que romper.

**Cómo te conectas:** por SSH normal desde tu máquina. El usuario por defecto de
las imágenes de Canonical Ubuntu en OCI es `ubuntu` (el `opc` es de Oracle
Linux):

```bash
ssh -i ~/.ssh/TU_CLAVE_PRIVADA ubuntu@<IP_PUBLICA_DE_LA_VM>
```

**Haz antes una copia del boot volume.** Es la red de seguridad más sólida: si
la actualización deja la máquina inarrancable, restauras y vuelves al punto de
partida sin perder la instancia ni su capacidad A1. En la consola: Compute →
Instance → *Boot volume* → el volumen → **Create Manual Backup**. Comprueba
antes en Billing si el almacenamiento de backups entra en tu Always Free.

**Prepara antes la consola serie**, que es cosa distinta: es la red de
seguridad para el caso de que tras un reinicio la máquina no levante la red y
te quedes sin SSH. No se usa para trabajar, pero si la necesitas y no está
creada, ya es tarde. Compute → Instances → tu instancia → *Console connection*
→ *Create local connection*.

**Trabaja siempre dentro de tmux.** Si la conexión SSH se corta a mitad de un
`do-release-upgrade` —wifi, el portátil que se suspende, lo que sea— el proceso
muere dejando paquetes a medio configurar. Dentro de tmux sobrevive y puedes
reengancharte:

```bash
sudo apt install -y tmux
tmux new -s upgrade
# si te desconectas: vuelves por SSH y haces  tmux attach -t upgrade
```

Ya dentro de tmux:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

Reconecta (`ssh` otra vez, y `tmux new -s upgrade`) y encadena las dos subidas
de versión (20.04 → 22.04 → 24.04):

```bash
sudo apt install -y update-manager-core
sudo do-release-upgrade          # a 22.04; responde a los prompts, reinicia
# reconecta por SSH y vuelve a entrar en tmux
sudo do-release-upgrade          # a 24.04
```

### ⚠️ Cuando pregunte por ficheros de configuración: CONSERVA los actuales

Durante la actualización aparecerán prompts del tipo *"Configuration file
`/etc/...` — install the package maintainer's version / keep the local
version"*. **Responde siempre conservar la versión local** (la opción por
defecto, normalmente `N`).

Las imágenes de Ubuntu para Oracle Cloud **no son Ubuntu genérico**: traen
configuración propia, en particular las reglas de `iptables` que permiten tu
conexión SSH y los ajustes de `cloud-init` y del agente de OCI. Si aceptas la
versión del paquete para `/etc/ssh/sshd_config` o `/etc/iptables/rules.v4`,
puedes **quedarte fuera de la máquina** en el siguiente reinicio.

Presta especial atención a cualquier prompt sobre:
- `/etc/ssh/sshd_config`
- `/etc/iptables/rules.v4` y `rules.v6`
- `/etc/cloud/cloud.cfg`

Verifica al terminar:
```bash
lsb_release -a          # debe decir 24.04
uname -m                # aarch64, confirma que es ARM
```

### Alternativa rápida si prefieres no actualizar ahora

`sudo pro attach` con una suscripción **Ubuntu Pro** (gratis para uso personal,
hasta 5 máquinas) reactiva los parches de seguridad de 20.04 hasta 2030. Cierra
el agujero de seguridad en dos minutos, **pero no resuelve lo de Docker**: sin
paquetes para focal seguirías sin poder desplegar. Sirve como parche temporal,
no como solución.

---

## 1. Abrir los puertos — los DOS sitios

Este es el paso donde se atasca todo el mundo con Oracle Cloud: hay **dos
cortafuegos independientes** y hay que abrir ambos. Con uno solo, la conexión
se queda colgada sin error claro.

### a) Security List de la VCN (consola web de Oracle)

Networking → Virtual Cloud Networks → tu VCN → Security Lists → la de la subred
→ **Add Ingress Rules**:

| Source CIDR | Protocolo | Puerto destino |
|---|---|---|
| `0.0.0.0/0` | TCP | 80 |
| `0.0.0.0/0` | TCP | 443 |

### b) Cortafuegos dentro de la VM

Las imágenes de Oracle traen `iptables` cerrado por defecto. Según el sistema:

**Oracle Linux / RHEL / Rocky:**
```bash
sudo firewall-cmd --permanent --add-service=http --add-service=https
sudo firewall-cmd --reload
```

**Ubuntu (imagen de Oracle):** trae reglas de iptables, no ufw activo.

**Nunca uses un número de posición fijo.** Las reglas se evalúan en orden y al
final hay un `REJECT` que descarta el resto; si insertas *después* de él, tu
regla no sirve de nada y no hay ningún error que te avise. Mira primero dónde
está:

```bash
sudo iptables -L INPUT -n --line-numbers
```

Localiza el número de línea del `REJECT ... reject-with icmp-host-prohibited` e
inserta **en esa misma posición**, para quedar justo antes (aquí se asume que
es la 5; usa el tuyo):

```bash
sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -L INPUT -n --line-numbers    # verifica ANTES de guardar
sudo netfilter-persistent save              # sin esto, se pierden al reiniciar
```

Nota: la política por defecto de la cadena es `ACCEPT`, así que equivocarse
borrando reglas no te deja fuera de la máquina — como mucho la deja demasiado
abierta un momento. Eso quita presión para experimentar aquí.

**Ojo con los duplicados.** Tras una actualización de versión es fácil acabar
con el conjunto de reglas repetido dos veces (guardar reglas ya cargadas). Las
copias tras el `REJECT` son inalcanzables y conviene borrarlas, por orden
descendente para que no se renumeren:

```bash
sudo iptables -D INPUT 10   # de mayor a menor
```

Verifica desde fuera de la VM, no desde dentro:
```bash
nc -vz auto-response.duckdns.org 443
```

---

## 2. Instalar Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
sudo systemctl enable --now docker     # para que arranque solo tras un reboot
```

Cierra la sesión SSH y vuelve a entrar para que el grupo `docker` surta efecto.

---

## 3. Traer el código

```bash
git clone -b oracle https://github.com/PomesTrees/insta-response.git
cd insta-response
```

---

## 4. Crear el `.env` en el servidor

**El `.env` no está en git y no debe estarlo.** Cópialo desde tu máquina:

```bash
# desde tu portátil, no desde la VM
scp .env usuario@<IP_PUBLICA>:~/insta-response/.env
```

Y en la VM, restringe permisos:
```bash
chmod 600 ~/insta-response/.env
```

---

## 5. Arrancar

El proxy y el bot son dos proyectos distintos que se comunican por una red
compartida. Hay que crearla una sola vez antes de nada:

```bash
docker network create web
```

Primero el proxy. **No vive en este repositorio**: es infraestructura
compartida por todos los sitios del servidor, así que está en `~/infra` (ver
su propio README). Es lo único que ocupa los puertos 80 y 443:

```bash
cd ~/infra
docker compose up -d
```

Y después el bot:

```bash
cd ~/insta-response
docker compose up -d --build
```

El dominio no se pasa por variable de entorno: está escrito en
`~/infra/Caddyfile`, fuera de este repositorio, donde vive junto al resto de
sitios del servidor.

Comprueba:
```bash
docker compose ps
docker compose logs -f bot
docker logs -f caddy
curl -s -o /dev/null -w "%{http_code}\n" https://auto-response.duckdns.org/
```

El primer arranque tarda algo más: Caddy está negociando el certificado. Si
falla, `docker logs caddy` lo dice con claridad (casi siempre es DNS que no ha
propagado o el puerto 80 cerrado).

---

## 6. Apuntar Meta al nuevo servidor

App Dashboard → Webhooks → objeto Instagram → **Edit**:

- **Callback URL:** `https://auto-response.duckdns.org/webhook`
- **Verify Token:** el mismo `IG_VERIFY_TOKEN` de siempre

Pulsa *Verify and Save*. Si da error, mira `docker compose logs -f bot`: ahora
verás la petición de verificación llegar en tiempo real.

Actualiza también App settings → Basic → **Privacy policy URL** a
`https://auto-response.duckdns.org/privacy`, porque la de Render dejará de servirse
cuando apagues ese servicio.

---

## 7. Comprobación final

Manda un DM real desde otra cuenta y observa:

```bash
docker compose logs -f bot
```

Debe aparecer `POST /webhook recibido`, `Firma válida` y `@cuenta respondió a
...`, y te debe llegar el aviso de Telegram.

---

## Operación diaria

```bash
docker compose logs -f bot          # ver logs en vivo
docker compose restart bot          # reiniciar solo la app
git pull && docker compose up -d --build   # desplegar cambios
docker compose down                 # parar todo (NO borra imágenes)
```

Los contenedores llevan `restart: unless-stopped`, así que vuelven solos tras un
reinicio de la VM siempre que el servicio de Docker esté habilitado (paso 2).

Los logs están limitados a 10 MB × 5 ficheros por contenedor. Sin ese límite
acabarían llenando el disco de la VM, que en el Free Tier no sobra.

**Nunca ejecutes `docker system prune` en esta máquina si compartes el Docker
con otros proyectos:** borra imágenes y capas que no son de este repo.

---

## Qué hacer con Render

Una vez que Oracle responda DMs correctamente durante un par de días, puedes
suspender el servicio de Render. Mientras tanto no estorba: no recibirá
webhooks, porque Meta solo entrega a la Callback URL configurada, que ya
apuntará a Oracle.

Si prefieres conservarlo como entorno de pruebas, déjalo con la rama `main` y
usa `oracle` solo para producción.
