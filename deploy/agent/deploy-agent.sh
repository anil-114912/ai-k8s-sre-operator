#!/usr/bin/env bash
# deploy-agent.sh — Build, push, and deploy the SRE log-reader agent
#
# Usage:
#   ./deploy/agent/deploy-agent.sh
#
# Prerequisites:
#   - aws cli configured with ECR push access
#   - kubectl pointing at the target cluster
#   - docker running
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

AWS_ACCOUNT="635066855817"
AWS_REGION="us-west-2"
ECR_REPO="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/ai-sre-agent"
IMAGE_TAG="latest"

echo "==> Logging into ECR..."
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Create ECR repo if it doesn't exist
aws ecr describe-repositories --repository-names ai-sre-agent --region "$AWS_REGION" 2>/dev/null \
  || aws ecr create-repository --repository-name ai-sre-agent --region "$AWS_REGION"

echo "==> Building agent image..."
docker build -t "${ECR_REPO}:${IMAGE_TAG}" -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"

echo "==> Pushing to ECR..."
docker push "${ECR_REPO}:${IMAGE_TAG}"

echo "==> Applying RBAC..."
kubectl apply -f "$SCRIPT_DIR/00-rbac.yaml"

echo "==> Deploying agent..."
kubectl apply -f "$SCRIPT_DIR/01-agent-deployment.yaml"

echo "==> Waiting for rollout..."
kubectl rollout status deployment/ai-sre-log-reader -n ai-sre --timeout=60s

echo ""
echo "✅ Agent deployed! Check logs with:"
echo "   kubectl logs -n ai-sre -l app=ai-sre-log-reader -f"
