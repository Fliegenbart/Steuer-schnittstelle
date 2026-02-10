#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
#  BelegSync – Deploy auf Hetzner GEX44
#  Voraussetzung: Ollama läuft bereits auf dem Host
#  Nutzung: sudo bash deploy.sh
# ═══════════════════════════════════════════════════════════
set -euo pipefail

APP_DIR="/opt/belegsync"
REPO="https://github.com/Fliegenbart/Steuer-schnittstelle.git"
NGINX_PORT=8480

echo "═══════════════════════════════════════════"
echo "  BelegSync Deploy"
echo "  Erreichbar auf Port $NGINX_PORT"
echo "═══════════════════════════════════════════"

# ── 1. Prüfe Voraussetzungen ──────────────────
echo ""
echo "[1/5] Prüfe Voraussetzungen..."

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
    echo "  ⚠ Llama 3.1 Modell nicht gefunden – ziehe es jetzt (kann 5-10 Min dauern)..."
    curl -f http://localhost:11434/api/pull -d '{"name": "llama3.1:8b-instruct-q4_K_M"}' || {
        echo "  ✗ Modell-Download fehlgeschlagen"
        exit 1
    }
fi
echo "  ✓ Llama 3.1 8B Modell verfügbar"

# Prüfe ob Ports schon belegt sind
if ss -tlnp | grep -q ":8470 " 2>/dev/null; then
    echo "  ⚠ Port 8470 belegt (alter Container?) → docker stop belegsync"
fi
if ss -tlnp | grep -q ":$NGINX_PORT " 2>/dev/null; then
    echo "  ⚠ Port $NGINX_PORT belegt → ss -tlnp | grep $NGINX_PORT"
fi

# ── 2. Repo klonen/aktualisieren ──────────────
echo ""
echo "[2/5] Lade Code..."

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
echo "[3/5] Konfiguration..."

if [ ! -f "$APP_DIR/.env" ]; then
    SECRET=$(openssl rand -hex 32)
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    sed -i "s|change-me-in-production|$SECRET|" "$APP_DIR/.env"
    echo "  ✓ .env erstellt (SECRET_KEY generiert)"
    echo "  ⚠ Optional: MAESN_API_KEY in $APP_DIR/.env eintragen"
else
    echo "  ✓ .env existiert bereits"
fi

# Daten-Verzeichnisse
mkdir -p "$APP_DIR/data" "$APP_DIR/uploads"

# ── 4. Docker bauen und starten ───────────────
echo ""
echo "[4/5] Docker Build & Start..."

cd "$APP_DIR"
docker compose build
docker compose up -d

# Warte auf Health Check
echo "  Warte auf Startup..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8470/api/health &>/dev/null; then
        echo "  ✓ BelegSync Container läuft"
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
echo "[5/5] Nginx..."

NGINX_CONF="/etc/nginx/sites-available/belegsync"
cp "$APP_DIR/scripts/nginx-belegsync.conf" "$NGINX_CONF"

# Symlink in sites-enabled
if [ ! -L /etc/nginx/sites-enabled/belegsync ]; then
    ln -s "$NGINX_CONF" /etc/nginx/sites-enabled/belegsync
fi

nginx -t && systemctl reload nginx
echo "  ✓ Nginx konfiguriert (Port $NGINX_PORT)"

# ── Fertig ────────────────────────────────────
SERVER_IP=$(curl -sf https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo "═══════════════════════════════════════════"
echo "  ✓ BelegSync ist live!"
echo ""
echo "  URL:    http://$SERVER_IP:$NGINX_PORT"
echo "  Health: http://$SERVER_IP:$NGINX_PORT/api/health"
echo "  Logs:   cd $APP_DIR && docker compose logs -f"
echo ""
echo "  Später Domain + SSL hinzufügen:"
echo "  1. DNS A-Record auf $SERVER_IP"
echo "  2. server_name in nginx-belegsync.conf setzen"
echo "  3. certbot --nginx -d belegsync.deine-domain.de"
echo "═══════════════════════════════════════════"
