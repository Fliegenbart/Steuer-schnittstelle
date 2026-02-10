#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
#  SteuerPilot – Deploy auf Hetzner GEX44
#  Voraussetzung: Ollama läuft bereits auf dem Host
# ═══════════════════════════════════════════════════════════
set -euo pipefail

DOMAIN="${1:-steuerpilot.deine-domain.de}"
APP_DIR="/opt/steuerpilot"
REPO="https://github.com/Fliegenbart/Steuer-schnittstelle.git"

echo "═══════════════════════════════════════════"
echo "  SteuerPilot Deploy"
echo "  Domain: $DOMAIN"
echo "═══════════════════════════════════════════"

# ── 1. Prüfe Voraussetzungen ──────────────────
echo ""
echo "[1/7] Prüfe Voraussetzungen..."

if ! command -v docker &>/dev/null; then
    echo "  ✗ Docker nicht installiert"
    echo "  → sudo apt update && sudo apt install -y docker.io docker-compose-plugin"
    exit 1
fi
echo "  ✓ Docker"

if ! command -v nginx &>/dev/null; then
    echo "  ✗ Nginx nicht installiert"
    echo "  → sudo apt install -y nginx"
    exit 1
fi
echo "  ✓ Nginx"

if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
    echo "  ✗ Ollama antwortet nicht auf localhost:11434"
    echo "  → Ollama starten: ollama serve"
    exit 1
fi
echo "  ✓ Ollama läuft"

# Prüfe ob Llama-Modell geladen ist
if ! curl -sf http://localhost:11434/api/tags | grep -q "llama3.1"; then
    echo "  ⚠ Llama 3.1 Modell nicht gefunden – ziehe es jetzt..."
    ollama pull llama3.1:8b-instruct-q4_K_M
fi
echo "  ✓ Llama 3.1 8B Modell verfügbar"

# ── 2. Repo klonen/aktualisieren ──────────────
echo ""
echo "[2/7] Lade Code..."

if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    git pull --ff-only
    echo "  ✓ Repository aktualisiert"
else
    git clone "$REPO" "$APP_DIR"
    cd "$APP_DIR"
    echo "  ✓ Repository geklont"
fi

# ── 3. .env erstellen ─────────────────────────
echo ""
echo "[3/7] Konfiguration..."

if [ ! -f "$APP_DIR/.env" ]; then
    SECRET=$(openssl rand -hex 32)
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    sed -i "s|change-me-in-production|$SECRET|" "$APP_DIR/.env"
    echo "  ✓ .env erstellt (SECRET_KEY generiert)"
    echo "  ⚠ MAESN_API_KEY manuell in $APP_DIR/.env eintragen!"
else
    echo "  ✓ .env existiert bereits"
fi

# Daten-Verzeichnisse
mkdir -p "$APP_DIR/data" "$APP_DIR/uploads"

# ── 4. Docker bauen und starten ───────────────
echo ""
echo "[4/7] Docker Build & Start..."

cd "$APP_DIR"
docker compose build --no-cache
docker compose up -d

# Warte auf Health Check
echo "  Warte auf Startup..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8470/api/health &>/dev/null; then
        echo "  ✓ SteuerPilot läuft auf Port 8470"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  ✗ Timeout – prüfe Logs: docker compose logs"
        exit 1
    fi
    sleep 2
done

# ── 5. Nginx konfigurieren ────────────────────
echo ""
echo "[5/7] Nginx..."

# Domain in Konfig einsetzen
NGINX_CONF="/etc/nginx/sites-available/steuerpilot"
cp "$APP_DIR/scripts/nginx-steuerpilot.conf" "$NGINX_CONF"
sed -i "s|steuerpilot.deine-domain.de|$DOMAIN|g" "$NGINX_CONF"

# Symlink in sites-enabled
if [ ! -L /etc/nginx/sites-enabled/steuerpilot ]; then
    ln -s "$NGINX_CONF" /etc/nginx/sites-enabled/steuerpilot
fi

# ── 6. SSL-Zertifikat ─────────────────────────
echo ""
echo "[6/7] SSL-Zertifikat..."

if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    # Temporär ohne SSL starten (damit certbot funktioniert)
    # Nginx-Konfig auf HTTP-only umstellen
    cat > "$NGINX_CONF" <<TMPEOF
server {
    listen 80;
    server_name $DOMAIN;
    location / {
        proxy_pass http://127.0.0.1:8470;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        client_max_body_size 50M;
    }
}
TMPEOF
    nginx -t && systemctl reload nginx

    # Certbot
    if ! command -v certbot &>/dev/null; then
        apt install -y certbot python3-certbot-nginx
    fi
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email admin@$DOMAIN

    # Vollständige Konfig wiederherstellen
    cp "$APP_DIR/scripts/nginx-steuerpilot.conf" "$NGINX_CONF"
    sed -i "s|steuerpilot.deine-domain.de|$DOMAIN|g" "$NGINX_CONF"
    echo "  ✓ SSL-Zertifikat erstellt"
else
    echo "  ✓ SSL-Zertifikat existiert bereits"
fi

nginx -t && systemctl reload nginx
echo "  ✓ Nginx konfiguriert"

# ── 7. Fertig ─────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
echo "  ✓ SteuerPilot ist live!"
echo ""
echo "  URL:    https://$DOMAIN"
echo "  Health: https://$DOMAIN/api/health"
echo "  Logs:   cd $APP_DIR && docker compose logs -f"
echo ""
echo "  Nächste Schritte:"
echo "  1. MAESN_API_KEY in $APP_DIR/.env eintragen"
echo "  2. docker compose restart"
echo "═══════════════════════════════════════════"
