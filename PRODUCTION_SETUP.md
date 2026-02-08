# ============================================
# CONFIGURACIÓN DE PRODUCCIÓN - BOT DERIV V2
# ============================================

## 🖥️ INFORMACIÓN DEL SERVIDOR

**VPS**: srv1078151  
**IP Pública**: 72.60.175.159  
**SO**: Ubuntu Linux  
**Entorno**: PRODUCCIÓN  

---

## 📋 CONSIDERACIONES IMPORTANTES PARA PRODUCCIÓN

### 1. **Seguridad**

#### Firewall (CRÍTICO)
Asegúrate de que SOLO estén abiertos estos puertos:

```bash
# Ver puertos abiertos actuales
sudo ufw status

# Si UFW no está activo, configurarlo:
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # HTTP (nginx)
sudo ufw allow 443/tcp     # HTTPS (nginx)
sudo ufw enable

# IMPORTANTE: NO abrir el puerto 8000 directamente
# El backend FastAPI debe estar detrás de nginx como proxy reverso
```

#### Acceso SSH
- ✅ Cambiar puerto SSH default (22) a uno aleatorio
- ✅ Deshabilitar login root
- ✅ Usar autenticación por clave (no password)
- ✅ Configurar fail2ban

```bash
# Ver intentos de acceso SSH
sudo tail -f /var/log/auth.log
```

### 2. **Dominio y SSL**

Ya tienes configurado `bot.jhonk.online` en el `.env`. Necesitas:

#### Configurar DNS (si aún no lo hiciste)
En tu proveedor de DNS (Cloudflare, GoDaddy, etc.):
```
Tipo: A
Nombre: bot (o el subdominio que quieras)
Valor: 72.60.175.159
TTL: 300
```

#### Configurar SSL con Let's Encrypt
```bash
# Instalar certbot
sudo apt install certbot python3-certbot-nginx

# Obtener certificado
sudo certbot --nginx -d bot.jhonk.online

# Auto-renovación (ya configurado automáticamente)
sudo systemctl status certbot.timer
```

### 3. **URLs de Producción**

El `.env` ya está actualizado con:
```bash
NEXT_PUBLIC_API_URL=http://72.60.175.159:8000  # Temporal (desarrollo)
NEXT_PUBLIC_WS_URL=ws://72.60.175.159:8000     # Temporal (desarrollo)

# Después de configurar nginx + SSL, cambiar a:
# NEXT_PUBLIC_API_URL=https://bot.jhonk.online
# NEXT_PUBLIC_WS_URL=wss://bot.jhonk.online
```

### 4. **Nginx como Reverse Proxy**

Crear configuración: `/etc/nginx/sites-available/deriv-bot`

```nginx
# Backend API (FastAPI)
upstream backend {
    server localhost:8000;
}

# Dashboard (Next.js)
upstream dashboard {
    server localhost:3000;
}

server {
    listen 80;
    server_name bot.jhonk.online;

    # Redirigir todo a HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name bot.jhonk.online;

    # SSL (certbot configurará automáticamente)
    ssl_certificate /etc/letsencrypt/live/bot.jhonk.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.jhonk.online/privkey.pem;

    # Dashboard (Next.js) en /
    location / {
        proxy_pass http://dashboard;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # API Backend en /api
    location /api {
        rewrite ^/api/(.*)$ /$1 break;
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket
    location /ws {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Logs
    access_log /var/log/nginx/deriv-bot.access.log;
    error_log /var/log/nginx/deriv-bot.error.log;
}
```

Activar configuración:
```bash
sudo ln -s /etc/nginx/sites-available/deriv-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 5. **Base de Datos PostgreSQL**

**Backup automático CRÍTICO para producción**:

```bash
# Crear script de backup
sudo nano /usr/local/bin/backup-deriv-db.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/deriv-bot"
DATE=$(date +%Y%m%d_%H%M%S)
DB_NAME="deriv_bot"
DB_USER="deriv_bot"

mkdir -p $BACKUP_DIR
pg_dump -U $DB_USER $DB_NAME | gzip > $BACKUP_DIR/deriv_bot_$DATE.sql.gz

# Mantener solo últimos 30 días
find $BACKUP_DIR -name "deriv_bot_*.sql.gz" -mtime +30 -delete

echo "Backup completado: deriv_bot_$DATE.sql.gz"
```

```bash
# Hacer ejecutable
sudo chmod +x /usr/local/bin/backup-deriv-db.sh

# Cron diario a las 3 AM
sudo crontab -e
# Agregar:
0 3 * * * /usr/local/bin/backup-deriv-db.sh >> /var/log/deriv-backup.log 2>&1
```

### 6. **Docker Compose en Producción**

El `docker-compose.yml` debe tener estas configuraciones de producción:

```yaml
services:
  bot-backend:
    restart: unless-stopped  # CRÍTICO
    mem_limit: 4g           # Limitar RAM
    cpus: 2                 # Limitar CPU
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    
  dashboard:
    restart: unless-stopped
    mem_limit: 2g
    
  postgres:
    restart: unless-stopped
    mem_limit: 4g
    volumes:
      - /var/lib/postgresql/data:/var/lib/postgresql/data  # Persistencia
    
  redis:
    restart: unless-stopped
    mem_limit: 512m
```

### 7. **Monitoreo y Logs**

```bash
# Ver logs en tiempo real
docker-compose logs -f bot-backend

# Ver uso de recursos
docker stats

# Espacio en disco (CRÍTICO)
df -h

# Limpiar logs viejos
docker system prune -a --volumes
```

### 8. **Variables de Entorno Sensibles**

En producción, considera usar **Docker Secrets** o **Vault** en lugar de `.env`:

```bash
# Crear archivo con token de Deriv
echo "sS279bYViNlHq3J" | docker secret create deriv_token -

# Usar en docker-compose.yml
secrets:
  - deriv_token
```

---

## ⚠️ CHECKLIST PRE-DEPLOYMENT EN PRODUCCIÓN

Antes de levantar el bot en producción:

- [ ] Firewall configurado (solo 22, 80, 443)
- [ ] SSH hardening (cambiar puerto, deshabilitar root)
- [ ] DNS apuntando a 72.60.175.159
- [ ] SSL configurado con Let's Encrypt
- [ ] Nginx reverse proxy activo
- [ ] Backups automáticos de PostgreSQL configurados
- [ ] Monitoreo con Prometheus + Grafana
- [ ] Alertas de Telegram funcionando
- [ ] Archivos `.env` con permisos 600 (solo root)
  ```bash
  sudo chmod 600 /var/www/jhonk/dreriv/.env
  ```
- [ ] Git configurado para NO commitear secrets
- [ ] Log rotation configurado
- [ ] Deriv en modo DEMO (no real todavía)

---

## 🚀 DEPLOYMENT SEGURO

### Paso 1: Primero en DEMO
```bash
cd /var/www/jhonk/dreriv
# Asegurarse que .env tiene DERIV_ACCOUNT_TYPE=demo
docker-compose up -d
```

### Paso 2: Monitorear 48 horas
```bash
# Ver logs continuamente
docker-compose logs -f

# Verificar trades en cuenta DEMO
```

### Paso 3: Solo después de validar → Producción Real
```bash
# Cambiar en .env:
DERIV_ACCOUNT_TYPE=real

# Restart
docker-compose restart bot-backend
```

---

## 📊 RECURSOS DEL VPS

Verifica que tienes suficientes recursos:

```bash
# CPU y RAM
htop

# Espacio en disco
df -h

# Verificar swap
free -h
```

**Recomendación**: Para trading 24/7, el VPS debería tener mínimo:
- 8GB RAM (tienes esto? verifica con `free -h`)
- 4 CPU cores
- 100GB SSD

---

¿Necesitas ayuda configurando alguno de estos aspectos de producción?
