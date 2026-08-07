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

## Requisito previo: un dominio

Let's Encrypt no emite certificados para direcciones IP, así que **hace falta un
subdominio apuntando a la IP pública de la VM**. Un registro `A`:

```
bot.tudominio.com.   A   <IP_PUBLICA_DE_LA_VM>
```

Comprueba que propagó antes de seguir, o Caddy fallará al pedir el certificado
y Let's Encrypt aplica límites de reintentos:

```bash
dig +short bot.tudominio.com
```

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
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save     # sin esto, se pierden al reiniciar
```

Verifica desde fuera de la VM, no desde dentro:
```bash
nc -vz bot.tudominio.com 443
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

```bash
DOMINIO=bot.tudominio.com docker compose up -d --build
```

Para que el dominio no haya que repetirlo en cada comando, ponlo en el `.env`:
```
DOMINIO=bot.tudominio.com
```

Comprueba:
```bash
docker compose ps
docker compose logs -f bot
curl -s -o /dev/null -w "%{http_code}\n" https://bot.tudominio.com/
```

El primer arranque tarda algo más: Caddy está negociando el certificado. Si
falla, `docker compose logs caddy` lo dice con claridad (casi siempre es DNS
que no ha propagado o el puerto 80 cerrado).

---

## 6. Apuntar Meta al nuevo servidor

App Dashboard → Webhooks → objeto Instagram → **Edit**:

- **Callback URL:** `https://bot.tudominio.com/webhook`
- **Verify Token:** el mismo `IG_VERIFY_TOKEN` de siempre

Pulsa *Verify and Save*. Si da error, mira `docker compose logs -f bot`: ahora
verás la petición de verificación llegar en tiempo real.

Actualiza también App settings → Basic → **Privacy policy URL** a
`https://bot.tudominio.com/privacy`, porque la de Render dejará de servirse
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
