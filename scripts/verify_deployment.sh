#!/usr/bin/env bash
# ============================================================
#  AI K8s SRE Operator — Post-Install Verification Script
#  Run after helm install / upgrade to confirm all components
#  are healthy and the API is responding correctly.
#
#  Usage:
#    ./scripts/verify_deployment.sh [API_URL] [NAMESPACE]
#
#  Examples:
#    ./scripts/verify_deployment.sh                                    # defaults
#    ./scripts/verify_deployment.sh http://localhost:8000              # local dev
#    ./scripts/verify_deployment.sh http://sre-operator.example.com ai-sre
# ============================================================

set -euo pipefail

# ---- Config ----------------------------------------------------------
API_URL="${1:-http://localhost:8000}"
NAMESPACE="${2:-default}"
TIMEOUT=120       # seconds to wait for each check
RETRY_INTERVAL=5  # seconds between retries

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

pass() { echo -e "${GREEN}  [PASS]${NC} $1"; }
fail() { echo -e "${RED}  [FAIL]${NC} $1"; FAILURES=$((FAILURES + 1)); }
warn() { echo -e "${YELLOW}  [WARN]${NC} $1"; }
info() { echo -e "  [INFO] $1"; }

FAILURES=0

echo ""
echo "============================================================"
echo "  AI K8s SRE Operator — Deployment Verification"
echo "  API: $API_URL"
echo "  Namespace: $NAMESPACE"
echo "============================================================"
echo ""

# ---- 1. kubectl availability ----------------------------------------
echo "--- Kubernetes connectivity ---"
if command -v kubectl &>/dev/null; then
  KUBE_VERSION=$(kubectl version --client --short 2>/dev/null | head -1 || echo "unknown")
  info "kubectl: $KUBE_VERSION"
else
  warn "kubectl not found — skipping K8s resource checks"
  KUBECTL_AVAILABLE=false
fi
KUBECTL_AVAILABLE="${KUBECTL_AVAILABLE:-true}"

# ---- 2. Pod health checks (if kubectl available) --------------------
if [ "$KUBECTL_AVAILABLE" = "true" ]; then
  echo ""
  echo "--- Pod status in namespace: $NAMESPACE ---"

  PODS=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null || echo "")
  if [ -z "$PODS" ]; then
    warn "No pods found in namespace $NAMESPACE — verify helm install completed"
  else
    echo "$PODS"
    NOT_RUNNING=$(echo "$PODS" | grep -v "Running\|Completed" | wc -l | tr -d ' ')
    if [ "$NOT_RUNNING" -gt 0 ]; then
      fail "$NOT_RUNNING pods are not in Running/Completed state"
    else
      pass "All pods are Running"
    fi

    # Check restart counts
    HIGH_RESTARTS=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
      | awk '{print $4}' | awk -F/ '{print $1}' | sort -n | tail -1 || echo "0")
    if [ "${HIGH_RESTARTS:-0}" -gt 5 ]; then
      warn "Highest pod restart count: $HIGH_RESTARTS (may indicate a crash loop)"
    fi
  fi

  # Check specific deployments
  echo ""
  echo "--- Deployment rollout status ---"
  for COMPONENT in api worker watcher; do
    DEP_NAME=$(kubectl get deployment -n "$NAMESPACE" -l "app.kubernetes.io/component=$COMPONENT" \
      --no-headers -o custom-columns=':metadata.name' 2>/dev/null | head -1 || echo "")
    if [ -n "$DEP_NAME" ]; then
      if kubectl rollout status deployment/"$DEP_NAME" -n "$NAMESPACE" --timeout=60s &>/dev/null; then
        pass "Deployment $DEP_NAME rolled out successfully"
      else
        fail "Deployment $DEP_NAME rollout did not complete within 60s"
      fi
    else
      info "Component $COMPONENT: no deployment found (may be optional)"
    fi
  done
fi

# ---- 3. API health check --------------------------------------------
echo ""
echo "--- API health check ---"
info "Waiting up to ${TIMEOUT}s for $API_URL/health ..."

ELAPSED=0
HTTP_RESPONSE=""
while [ $ELAPSED -lt $TIMEOUT ]; do
  HTTP_RESPONSE=$(curl -sf --max-time 5 "$API_URL/health" 2>/dev/null || true)
  if [ -n "$HTTP_RESPONSE" ]; then
    break
  fi
  sleep $RETRY_INTERVAL
  ELAPSED=$((ELAPSED + RETRY_INTERVAL))
done

if [ -n "$HTTP_RESPONSE" ]; then
  pass "API health endpoint responded"
  info "Response: $HTTP_RESPONSE"

  # Check status field
  STATUS=$(echo "$HTTP_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
  if [ "$STATUS" = "ok" ]; then
    pass "API status: ok"
  else
    fail "API status: $STATUS (expected 'ok')"
  fi

  # Check demo_mode
  DEMO=$(echo "$HTTP_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('demo_mode', '?'))" 2>/dev/null || echo "?")
  if [ "$DEMO" = "True" ] || [ "$DEMO" = "true" ]; then
    warn "Running in DEMO mode — no real K8s cluster connected"
  else
    pass "Running in live cluster mode"
  fi
else
  fail "API health endpoint did not respond within ${TIMEOUT}s"
fi

# ---- 4. Knowledge base loaded check ---------------------------------
echo ""
echo "--- Knowledge base ---"
KB_RESPONSE=$(curl -sf --max-time 10 "$API_URL/api/v1/kb/patterns?limit=1" 2>/dev/null || echo "")
if [ -n "$KB_RESPONSE" ]; then
  KB_COUNT=$(echo "$KB_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total', len(d.get('patterns',[]))))" 2>/dev/null || echo "0")
  if [ "${KB_COUNT:-0}" -gt 0 ]; then
    pass "Knowledge base loaded ($KB_COUNT patterns)"
  else
    warn "Knowledge base appears empty — check knowledge/failures/*.yaml"
  fi
else
  warn "Could not reach KB endpoint (API may not be fully up yet)"
fi

# ---- 5. Detector availability check --------------------------------
echo ""
echo "--- Detectors ---"
DETECT_RESPONSE=$(curl -sf --max-time 10 "$API_URL/api/v1/scan?clear=false" 2>/dev/null || echo "")
if [ -n "$DETECT_RESPONSE" ]; then
  pass "Scan endpoint accessible (detectors operational)"
else
  warn "Scan endpoint did not respond — detectors may not be ready"
fi

# ---- 6. Integration config check ------------------------------------
echo ""
echo "--- Integration status ---"
INTEG_RESPONSE=$(curl -sf --max-time 10 "$API_URL/api/v1/integrations/status" 2>/dev/null || echo "")
if [ -n "$INTEG_RESPONSE" ]; then
  ENABLED=$(echo "$INTEG_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('total_enabled', 0))" 2>/dev/null || echo "?")
  info "Active integrations: $ENABLED (Slack, PagerDuty, Jira)"
else
  info "Integrations endpoint not reachable (not critical)"
fi

# ---- 7. Summary -----------------------------------------------------
echo ""
echo "============================================================"
if [ "$FAILURES" -eq 0 ]; then
  echo -e "${GREEN}  VERIFICATION PASSED${NC} — Operator is healthy"
else
  echo -e "${RED}  VERIFICATION FAILED — $FAILURES check(s) failed${NC}"
  echo ""
  echo "  Troubleshooting:"
  echo "    kubectl logs -n $NAMESPACE -l app.kubernetes.io/name=ai-k8s-sre-operator"
  echo "    kubectl describe pods -n $NAMESPACE"
  echo "    curl $API_URL/api/v1/debug/provider"
fi
echo "============================================================"
echo ""

exit $FAILURES
