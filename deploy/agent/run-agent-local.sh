#!/usr/bin/env bash
# run-agent-local.sh — Run the log-reader agent locally for testing.
#
# This uses kubectl proxy to access the K8s API and sends reports
# to your local operator at localhost:8000.
#
# Usage:
#   ./deploy/agent/run-agent-local.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Start kubectl proxy in background (gives us http://localhost:8001 for K8s API)
echo "==> Starting kubectl proxy on :8001..."
kubectl proxy --port=8001 &
PROXY_PID=$!
trap "kill $PROXY_PID 2>/dev/null" EXIT
sleep 2

echo "==> Starting SRE log-reader agent..."
echo "    Operator API: http://localhost:8000"
echo "    K8s API:      http://localhost:8001 (via kubectl proxy)"
echo "    Namespaces:   dev,qa,default"
echo ""

OPERATOR_API_URL="http://localhost:8000" \
KUBERNETES_API_URL="http://localhost:8001" \
TARGET_NAMESPACES="dev,qa,default" \
TAIL_LINES="100" \
REPORT_INTERVAL="30" \
LOG_LEVEL="INFO" \
  python3 "$SCRIPT_DIR/log_reader_agent.py"
