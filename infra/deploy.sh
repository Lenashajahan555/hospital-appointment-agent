#!/usr/bin/env bash
# Deploys APIM (Developer tier) + Azure OpenAI, then writes ../.env for the agent/GUI.
# Usage: ./deploy.sh <unique-suffix> <publisher-email> [location]
# NOTE: APIM Developer provisioning typically takes 30-45 minutes.
set -euo pipefail

SUFFIX="${1:?usage: deploy.sh <unique-suffix> <publisher-email> [location]}"
EMAIL="${2:?usage: deploy.sh <unique-suffix> <publisher-email> [location]}"
LOCATION="${3:-eastus2}"

RG="rg-apim-agent-${SUFFIX}"
APIM="apim-agent-${SUFFIX}"
AOAI="aoai-agent-${SUFFIX}"
HERE="$(cd "$(dirname "$0")" && pwd)"

az account show >/dev/null 2>&1 || az login
echo ">> Resource group ${RG} (${LOCATION})"
az group create -n "$RG" -l "$LOCATION" -o none

echo ">> Deploying Bicep (APIM Developer is slow: ~30-45 min)"
az deployment group create \
  -g "$RG" \
  -f "$HERE/main.bicep" \
  -p apimName="$APIM" openAiName="$AOAI" publisherEmail="$EMAIL" \
  -o none

GATEWAY=$(az deployment group show -g "$RG" -n main --query properties.outputs.gatewayUrl.value -o tsv)
DEPLOYMENT=$(az deployment group show -g "$RG" -n main --query properties.outputs.deploymentName.value -o tsv)

echo ">> Fetching subscription key"
SUB_ID=$(az account show --query id -o tsv)
KEY=$(az rest --method post \
  --url "https://management.azure.com/subscriptions/${SUB_ID}/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}/subscriptions/agent-sub/listSecrets?api-version=2023-05-01-preview" \
  --query primaryKey -o tsv)

cat > "$HERE/../.env" <<EOF
APIM_GATEWAY_URL=${GATEWAY}
APIM_SUBSCRIPTION_KEY=${KEY}
AOAI_DEPLOYMENT=${DEPLOYMENT}
AOAI_API_VERSION=2024-06-01
EOF

echo ">> Done. Wrote .env. Tear down later with: az group delete -n ${RG} --yes"
