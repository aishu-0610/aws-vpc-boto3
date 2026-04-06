#!/usr/bin/env bash
# run.sh  —  FocusGate one-shot startup
# Usage: bash run.sh

set -e
cd "$(dirname "$0")"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FocusGate — DNS Productivity Filter"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Init DB + seed
echo "[1/3] Initialising database..."
python backend/db.py

# 2. Start FastAPI in background
echo "[2/3] Starting API server on :8000..."
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!
sleep 1

# 3. Start DNS engine in background
echo "[3/3] Starting DNS proxy on port 5353 (dev)..."
echo "      → For production port 53: sudo DNS_PORT=53 python backend/dns_engine.py"
DNS_PORT=5353 python backend/dns_engine.py &
DNS_PID=$!
sleep 0.5

echo ""
echo "✅  All services running"
echo "   Dashboard  →  http://localhost:8501"
echo "   API docs   →  http://localhost:8000/docs"
echo "   DNS proxy  →  127.0.0.1:5353"
echo ""
echo "   Test DNS:  dig @127.0.0.1 -p 5353 youtube.com"
echo "              dig @127.0.0.1 -p 5353 google.com"
echo ""

# Start Streamlit (foreground — keeps script alive)
streamlit run frontend/app.py --server.port 8501

# Cleanup background processes on exit
trap "kill $API_PID $DNS_PID 2>/dev/null; echo 'Stopped.'" EXIT
