#!/usr/bin/env bash
# Deploy Hath0r MCP service to AWS App Runner
# Usage: ./deploy/aws/deploy.sh

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-2}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-066949051380}"
SERVICE_NAME="hath0r-mcp"
DOMAIN_NAME="mcp.hath0r-cli.com"
HOSTED_ZONE_ID="Z07798482NZ7OZ8H509NH"
ECR_REPO="hath0r/mcp"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_URI="${ECR_REGISTRY}/${ECR_REPO}:latest"

echo "=================================================================="
echo "⚡ Deploying Hath0r MCP to AWS App Runner (${AWS_REGION})"
echo "   Target Domain: ${DOMAIN_NAME}"
echo "   ECR Registry:  ${ECR_REGISTRY}"
echo "=================================================================="

# 1. ECR Login
echo "[1/6] Logging into Amazon ECR..."
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

# 2. Ensure ECR Repo Exists
echo "[2/6] Verifying ECR repository..."
aws ecr describe-repositories --repository-names "${ECR_REPO}" --region "${AWS_REGION}" >/dev/null 2>&1 || \
aws ecr create-repository --repository-name "${ECR_REPO}" --region "${AWS_REGION}" >/dev/null

# 3. Build & Push Image
echo "[3/6] Building and pushing linux/amd64 Docker image..."
docker build --platform linux/amd64 -t "${IMAGE_URI}" .
docker push "${IMAGE_URI}"

# 4. Check or Create App Runner Service
echo "[4/6] Checking App Runner service status..."
SERVICE_ARN=$(aws apprunner list-services --region "${AWS_REGION}" --query "ServiceSummaryList[?ServiceName=='${SERVICE_NAME}'].ServiceArn" --output text)

if [ -z "${SERVICE_ARN}" ]; then
  echo "Creating new App Runner service: ${SERVICE_NAME}..."
  aws apprunner create-service \
    --service-name "${SERVICE_NAME}" \
    --region "${AWS_REGION}" \
    --source-configuration "{
      \"ImageRepository\": {
        \"ImageIdentifier\": \"${IMAGE_URI}\",
        \"ImageConfiguration\": {
          \"Port\": \"8083\",
          \"RuntimeEnvironmentVariables\": {
            \"HATH0R_MCP_ENVIRONMENT\": \"local\",
            \"HATH0R_MCP_KNOWLEDGE_ROOT\": \"/app/knowledgebase/canonical\"
          }
        },
        \"ImageRepositoryType\": \"ECR\"
      },
      \"AuthenticationConfiguration\": {
        \"AccessRoleArn\": \"arn:aws:iam::${AWS_ACCOUNT_ID}:role/AppRunnerECRAccessRole\"
      },
      \"AutoDeploymentsEnabled\": false
    }" \
    --instance-configuration '{"Cpu": "1024", "Memory": "2048"}' \
    --health-check-configuration '{"Protocol": "HTTP", "Path": "/ready", "Interval": 10, "Timeout": 5, "HealthyThreshold": 1, "UnhealthyThreshold": 5}'
else
  echo "App Runner service exists (${SERVICE_ARN}). Triggering deployment..."
  aws apprunner start-deployment --service-arn "${SERVICE_ARN}" --region "${AWS_REGION}" || true
fi

echo "=================================================================="
echo "✅ Deployment initiated for ${SERVICE_NAME} on AWS App Runner!"
echo "=================================================================="
