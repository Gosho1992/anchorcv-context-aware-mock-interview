#!/bin/bash
# AnchorCV Backend - Server Setup & Deploy Script
# Run this on your VPS (178.104.48.216) as root or sudo user

set -e

DEPLOY_DIR="/var/www/anchorcv"
BACKEND_DIR="$DEPLOY_DIR/anchorcv-backend"
FRONTEND_DIR="$DEPLOY_DIR/anchorcv-frontend"
SERVICE_NAME="anchorcv"

echo "=== AnchorCV Deploy Script ==="

# 1. Install system dependencies (run once)
install_deps() {
    echo "[1/5] Installing system packages..."
    apt-get update -qq
    apt-get install -y python3 python3-pip python3-venv nginx
}

# 2. Setup directory and copy files
setup_dirs() {
    echo "[2/5] Setting up directories..."
    mkdir -p "$BACKEND_DIR"
    mkdir -p "$FRONTEND_DIR"
}

# 3. Install Python dependencies
install_python() {
    echo "[3/5] Installing Python dependencies..."
    cd "$BACKEND_DIR"
    if [ ! -d "../venv" ]; then
        python3 -m venv "$DEPLOY_DIR/venv"
    fi
    "$DEPLOY_DIR/venv/bin/pip" install -r requirements.txt --quiet
}

# 4. Install systemd service
install_service() {
    echo "[4/5] Installing systemd service..."
    cp "$BACKEND_DIR/anchorcv.service" /etc/systemd/system/anchorcv.service
    systemctl daemon-reload
    systemctl enable anchorcv
    systemctl restart anchorcv
    echo "Backend service status:"
    systemctl status anchorcv --no-pager
}

# 5. Setup Nginx to serve frontend + proxy backend
setup_nginx() {
    echo "[5/5] Configuring Nginx..."
    cat > /etc/nginx/sites-available/anchorcv << 'NGINX'
server {
    listen 80;
    server_name _;

    # Serve frontend static files
    root /var/www/anchorcv/anchorcv-frontend/dist;
    index index.html;

    # API proxy to FastAPI backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
        client_max_body_size 20M;
    }

    # React Router - send all other requests to index.html
    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINX

    ln -sf /etc/nginx/sites-available/anchorcv /etc/nginx/sites-enabled/anchorcv
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl reload nginx
    echo "Nginx configured successfully!"
}

# --- MAIN ---
echo ""
echo "Choose action:"
echo "  1) Full fresh install (first time setup)"
echo "  2) Restart backend service only"
echo "  3) Check service status"
read -p "Enter choice [1-3]: " choice

case $choice in
    1)
        install_deps
        setup_dirs
        install_python
        install_service
        setup_nginx
        echo ""
        echo "=== DONE! ==="
        echo "Backend running at: http://178.104.48.216:8000"
        echo "Frontend at:        http://178.104.48.216"
        ;;
    2)
        systemctl restart anchorcv
        systemctl status anchorcv --no-pager
        ;;
    3)
        systemctl status anchorcv --no-pager
        echo ""
        echo "Recent logs:"
        journalctl -u anchorcv -n 30 --no-pager
        ;;
    *)
        echo "Invalid choice"
        ;;
esac
