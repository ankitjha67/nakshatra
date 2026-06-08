#!/usr/bin/env bash
# Deploy Jyotish Cloud to GCP Cloud Run. Edit the vars, then: bash deploy/gcp_deploy.sh
# Prereqs: gcloud CLI authenticated (gcloud auth login) and billing enabled.
set -euo pipefail

# ---------------------------------------------------------------------------- #
# CONFIG — edit these
# ---------------------------------------------------------------------------- #
PROJECT_ID="your-gcp-project"
REGION="asia-south1"            # Mumbai; pick what's near your users
SERVICE="jyotish-api"
REPO="jyotish"                  # Artifact Registry repo name

LLM_PROVIDER="vertex"           # vertex | anthropic | openai
ANTHROPIC_API_KEY=""            # only if LLM_PROVIDER=anthropic
OPENAI_API_KEY=""               # only if LLM_PROVIDER=openai
ADMIN_API_KEY="$(openssl rand -hex 24)"
INTERNAL_TOKEN="$(openssl rand -hex 24)"
# ---------------------------------------------------------------------------- #

gcloud config set project "$PROJECT_ID"

echo "==> Enabling APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com firestore.googleapis.com \
  cloudtasks.googleapis.com aiplatform.googleapis.com

echo "==> Firestore (Native mode) — ignore error if it already exists"
gcloud firestore databases create --location="$REGION" 2>/dev/null || true

echo "==> Artifact Registry repo"
gcloud artifacts repositories create "$REPO" --repository-format=docker \
  --location="$REGION" 2>/dev/null || true

echo "==> Secrets"
create_secret () { # name value
  printf '%s' "$2" | gcloud secrets create "$1" --data-file=- 2>/dev/null \
    || printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=-
}
create_secret admin-api-key  "$ADMIN_API_KEY"
create_secret internal-token "$INTERNAL_TOKEN"
[ -n "$ANTHROPIC_API_KEY" ] && create_secret anthropic-api-key "$ANTHROPIC_API_KEY" || true
[ -n "$OPENAI_API_KEY" ]    && create_secret openai-api-key    "$OPENAI_API_KEY"    || true

echo "==> Cloud Tasks queue (async readings)"
gcloud tasks queues create readings --location="$REGION" 2>/dev/null || true

IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$SERVICE:$(date +%Y%m%d-%H%M%S)"
echo "==> Build image: $IMAGE"
gcloud builds submit --tag "$IMAGE" .

QUEUE="projects/$PROJECT_ID/locations/$REGION/queues/readings"
SECRET_ARGS="ADMIN_API_KEY=admin-api-key:latest,INTERNAL_TOKEN=internal-token:latest"
[ -n "$ANTHROPIC_API_KEY" ] && SECRET_ARGS="$SECRET_ARGS,ANTHROPIC_API_KEY=anthropic-api-key:latest"
[ -n "$OPENAI_API_KEY" ]    && SECRET_ARGS="$SECRET_ARGS,OPENAI_API_KEY=openai-api-key:latest"

echo "==> Deploy to Cloud Run"
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" --region "$REGION" --allow-unauthenticated \
  --concurrency 20 --cpu 1 --memory 512Mi --min-instances 0 --max-instances 10 \
  --set-env-vars "APP_ENV=prod,LLM_PROVIDER=$LLM_PROVIDER,STORE_BACKEND=firestore,FIRESTORE_PROJECT=$PROJECT_ID,VERTEX_PROJECT=$PROJECT_ID,VERTEX_LOCATION=$REGION,CLOUD_TASKS_QUEUE=$QUEUE,CORS_ORIGINS=https://$PROJECT_ID.web.app,DEFAULT_USER_TIER=free,VERIFY_TOKEN_REVOCATION=true,REQUIRE_EMAIL_VERIFIED=true" \
  --update-secrets "$SECRET_ARGS"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo "==> Setting WORKER_BASE_URL=$URL (enables Cloud Tasks callback)"
gcloud run services update "$SERVICE" --region "$REGION" \
  --update-env-vars "WORKER_BASE_URL=$URL"

cat <<EOF

Deployed: $URL
  Health:  curl $URL/health
  Tiers:   curl $URL/v1/tiers
  Admin key (save it):  $ADMIN_API_KEY

NOTE: STORE_BACKEND=firestore requires you to implement FirestoreStore first
(see ARCHITECTURE.md §7). Until then, deploy with STORE_BACKEND=memory to smoke-test.
Grant the Cloud Run service account roles/datastore.user,
roles/cloudtasks.enqueuer, roles/aiplatform.user, roles/secretmanager.secretAccessor.
EOF
