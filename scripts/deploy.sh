#!/usr/bin/env bash
# Redeploy homesol: the API to AWS Lambda and the web app to Amplify Hosting.
# One-time resources (IAM role, function, function URL, Amplify app, DynamoDB
# table) already exist; this only ships new code.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
FUNCTION="homesol-api"
AMPLIFY_APP_NAME="homesol"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="${ROOT}/api/build"

echo "== Packaging API"
rm -rf "${BUILD}/pkg" "${BUILD}/api.zip"
mkdir -p "${BUILD}/pkg"
"${ROOT}/api/.venv/bin/pip" install -q --target "${BUILD}/pkg" \
  --platform manylinux2014_aarch64 --python-version 3.13 --implementation cp --only-binary=:all: \
  strands-agents fastapi python-dotenv mangum amazon-transcribe httpx numpy tifffile
cp -r "${ROOT}/api/homesol" "${ROOT}/api/data" "${ROOT}/api/lambda_handler.py" "${BUILD}/pkg/"
find "${BUILD}/pkg" -name "__pycache__" -type d -prune -exec rm -rf {} +
(cd "${BUILD}/pkg" && zip -qr ../api.zip .)

echo "== Updating Lambda"
# The package is too large to upload reliably in one request, so it goes through S3.
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="homesol-deploy-${ACCOUNT}"
aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null || aws s3 mb "s3://${BUCKET}" --region "${REGION}"
aws s3 cp --only-show-errors "${BUILD}/api.zip" "s3://${BUCKET}/api.zip"
aws lambda update-function-code --region "${REGION}" --function-name "${FUNCTION}" \
  --s3-bucket "${BUCKET}" --s3-key api.zip --query 'LastUpdateStatus' --output text
aws lambda wait function-updated-v2 --region "${REGION}" --function-name "${FUNCTION}"

# Bring the function's settings in line with api/.env, keeping everything else it has: the Google
# Maps key, and which Bedrock model does which job. A model variable missing from api/.env is
# removed from the function, so the default in the code applies in both places.
if [[ -f "${ROOT}/api/.env" ]]; then
echo "== Syncing settings to the function"
ENVIRONMENT="$(aws lambda get-function-configuration --region "${REGION}" --function-name "${FUNCTION}" --query 'Environment.Variables' --output json \
  | ENV_FILE="${ROOT}/api/.env" python3 -c '
import json, os, sys
live = json.load(sys.stdin) or {}
local = {}
for line in open(os.environ["ENV_FILE"]):
    name, sep, value = line.strip().partition("=")
    if sep and value and not name.startswith("#"):
        local[name] = value
if "GOOGLE_MAPS_API_KEY" in local:
    live["GOOGLE_MAPS_API_KEY"] = local["GOOGLE_MAPS_API_KEY"]
for name in ("BEDROCK_AGENT_MODEL_ID", "BEDROCK_SPECIALIST_MODEL_ID", "BEDROCK_VISION_MODEL_ID"):
    if name in local:
        live[name] = local[name]
    else:
        live.pop(name, None)
print(json.dumps({"Variables": live}))')"
aws lambda update-function-configuration --region "${REGION}" --function-name "${FUNCTION}" \
  --environment "${ENVIRONMENT}" --query 'LastUpdateStatus' --output text
aws lambda wait function-updated-v2 --region "${REGION}" --function-name "${FUNCTION}"
fi

API_URL="$(aws lambda get-function-url-config --region "${REGION}" --function-name "${FUNCTION}" --query 'FunctionUrl' --output text)"
API_URL="${API_URL%/}"

echo "== Building web against ${API_URL}"
(cd "${ROOT}/web" && NEXT_PUBLIC_API_URL="${API_URL}" pnpm build)
rm -f "${BUILD}/web.zip"
(cd "${ROOT}/web/out" && zip -qr "${BUILD}/web.zip" .)

echo "== Deploying to Amplify"
APP_ID="$(aws amplify list-apps --region "${REGION}" --query "apps[?name=='${AMPLIFY_APP_NAME}'].appId | [0]" --output text)"
read -r JOB_ID UPLOAD_URL <<<"$(aws amplify create-deployment --region "${REGION}" --app-id "${APP_ID}" --branch-name main --query '[jobId,zipUploadUrl]' --output text)"
curl -sf -o /dev/null -T "${BUILD}/web.zip" -H "Content-Type: application/zip" "${UPLOAD_URL}"
aws amplify start-deployment --region "${REGION}" --app-id "${APP_ID}" --branch-name main --job-id "${JOB_ID}" --query 'jobSummary.status' --output text
for _ in $(seq 1 40); do
  STATUS="$(aws amplify get-job --region "${REGION}" --app-id "${APP_ID}" --branch-name main --job-id "${JOB_ID}" --query 'job.summary.status' --output text)"
  [[ "${STATUS}" == "SUCCEED" || "${STATUS}" == "FAILED" ]] && break
  sleep 5
done
echo "Amplify: ${STATUS}"
echo "Site: https://main.${APP_ID}.amplifyapp.com"
[[ "${STATUS}" == "SUCCEED" ]]
