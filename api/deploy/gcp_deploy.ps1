# Deploy Jyotish Cloud to GCP Cloud Run from PowerShell.
# Edit the CONFIG block, then run:   .\deploy\gcp_deploy.ps1
# Prereqs: gcloud installed + authenticated (gcloud auth login), billing enabled.
# If scripts are blocked, run once:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#
# Cloud Build builds the image remotely, so you do NOT need Docker on Windows.

$ErrorActionPreference = "Continue"   # let harmless "already exists" errors pass

# ----------------------------- CONFIG: edit these -----------------------------
$ProjectId       = "nakshatra-prod"
$Region          = "asia-south1"          # Mumbai
$Service         = "jyotish-api"
$Repo            = "jyotish"               # Artifact Registry repo
$LlmProvider     = "vertex"               # vertex | anthropic | openai
$AnthropicApiKey = ""                      # only if LlmProvider = anthropic
$OpenAiApiKey    = ""                      # only if LlmProvider = openai
# For the FIRST smoke test, memory store + mock LLM works with zero extra setup.
# Switch STORE_BACKEND to "firestore" once you've implemented FirestoreStore (Phase 2).
$StoreBackend    = "memory"               # memory | firestore
# ------------------------------------------------------------------------------

function New-Token { -join ((1..24) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) }) }
$AdminApiKey   = New-Token
$InternalToken = New-Token

gcloud config set project $ProjectId

Write-Host "==> Enabling APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com `
  cloudbuild.googleapis.com secretmanager.googleapis.com firestore.googleapis.com `
  cloudtasks.googleapis.com aiplatform.googleapis.com

Write-Host "==> Firestore (Native) - ignore error if it already exists"
gcloud firestore databases create --location=$Region 2>$null

Write-Host "==> Artifact Registry repo"
gcloud artifacts repositories create $Repo --repository-format=docker --location=$Region 2>$null

function Set-Secret($Name, $Value) {
  $tmp = New-TemporaryFile
  [IO.File]::WriteAllText($tmp.FullName, $Value)   # no BOM, no trailing newline
  gcloud secrets create $Name --data-file=$tmp.FullName 2>$null
  if ($LASTEXITCODE -ne 0) { gcloud secrets versions add $Name --data-file=$tmp.FullName }
  Remove-Item $tmp.FullName
}

Write-Host "==> Secrets"
Set-Secret "admin-api-key"  $AdminApiKey
Set-Secret "internal-token" $InternalToken
if ($AnthropicApiKey) { Set-Secret "anthropic-api-key" $AnthropicApiKey }
if ($OpenAiApiKey)    { Set-Secret "openai-api-key"    $OpenAiApiKey }

Write-Host "==> Cloud Tasks queue (async readings)"
gcloud tasks queues create readings --location=$Region 2>$null

$Image = "$Region-docker.pkg.dev/$ProjectId/$Repo/${Service}:$(Get-Date -Format yyyyMMdd-HHmmss)"
Write-Host "==> Build image: $Image"
gcloud builds submit --tag $Image .

$Queue = "projects/$ProjectId/locations/$Region/queues/readings"

$SecretArgs = "ADMIN_API_KEY=admin-api-key:latest,INTERNAL_TOKEN=internal-token:latest"
if ($AnthropicApiKey) { $SecretArgs += ",ANTHROPIC_API_KEY=anthropic-api-key:latest" }
if ($OpenAiApiKey)    { $SecretArgs += ",OPENAI_API_KEY=openai-api-key:latest" }

$EnvVars = "APP_ENV=prod,LLM_PROVIDER=$LlmProvider,STORE_BACKEND=$StoreBackend," +
           "FIRESTORE_PROJECT=$ProjectId,VERTEX_PROJECT=$ProjectId,VERTEX_LOCATION=$Region," +
           "CLOUD_TASKS_QUEUE=$Queue"

Write-Host "==> Deploy to Cloud Run"
gcloud run deploy $Service `
  --image $Image --region $Region --allow-unauthenticated `
  --concurrency 20 --cpu 1 --memory 512Mi --min-instances 0 --max-instances 10 `
  --set-env-vars $EnvVars `
  --update-secrets $SecretArgs

$Url = gcloud run services describe $Service --region $Region --format='value(status.url)'
Write-Host "==> Setting WORKER_BASE_URL=$Url (enables Cloud Tasks callback)"
gcloud run services update $Service --region $Region --update-env-vars "WORKER_BASE_URL=$Url"

Write-Host ""
Write-Host "Deployed: $Url"
Write-Host "  Health:  curl.exe $Url/health"
Write-Host "  Tiers:   curl.exe $Url/v1/tiers"
Write-Host "  Admin key (SAVE THIS): $AdminApiKey"
Write-Host ""
Write-Host "Grant the Cloud Run service account these roles when you move to Firestore/Vertex:"
Write-Host "  roles/datastore.user  roles/cloudtasks.enqueuer  roles/aiplatform.user  roles/secretmanager.secretAccessor"
