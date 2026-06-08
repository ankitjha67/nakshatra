# Deploying on AWS / Azure / Oracle

The app is a plain container and is cloud-agnostic. Swap three env-driven
concerns - **host**, **LLM provider**, **store** - and you're on a different
cloud. Below are the equivalents and the one or two gotchas each.

GCP is covered by `gcp_deploy.sh`. The Terraform skeleton (`terraform/`) targets
GCP but the resource shapes map 1:1 to the services here.

---

## AWS

| Concern | Service |
|---|---|
| Run container | **App Runner** (simplest) or ECS Fargate |
| LLM | **Bedrock** (Claude), set `LLM_PROVIDER=anthropic` via Bedrock SDK, or call the Anthropic API directly |
| Store | **DynamoDB** (api_keys, usage, cache, jobs tables) |
| Secrets | Secrets Manager (inject as env) |
| Async | **SQS** → a small consumer hitting `/internal/run-reading`, or run in-process |
| Tiered quota (managed) | **API Gateway usage plans** - per-key throttle + quota out of the box |

Steps: `docker build` → push to ECR → `aws apprunner create-service` pointing at
the image, with env vars. Implement a `DynamoStore` mirroring `MemoryStore`'s
methods. If you front the service with API Gateway usage plans, the gateway can
enforce per-tier rate/quota and you let the app trust the validated key, less
metering code to maintain.

Bedrock note: to use `LLM_PROVIDER=anthropic` against Bedrock, either point the
Anthropic SDK at Bedrock (`anthropic[bedrock]`, `AnthropicBedrock` client) or add
a thin `BedrockProvider` alongside the others in `app/llm.py`.

---

## Azure

| Concern | Service |
|---|---|
| Run container | **Container Apps** (scale-to-zero like Cloud Run) |
| LLM | **Azure OpenAI** - add an `AzureOpenAIProvider` (same shape as `OpenAIProvider`, with endpoint + deployment name) |
| Store | **Cosmos DB** (SQL API) |
| Secrets | Key Vault (referenced by Container Apps secrets) |
| Async | **Service Bus** queue → consumer → `/internal/run-reading` |
| Tiered quota (managed) | **API Management products** - Basic/Pro/Business as APIM products with quota+rate policies; subscription keys = your API keys |

Steps: push to ACR → `az containerapp create` with env + secrets. APIM is the
clean way to sell tiers on Azure: define a *product* per tier with quota/rate
policies, and let subscribers self-serve keys.

---

## Oracle (OCI)

| Concern | Service |
|---|---|
| Run container | **Container Instances** (or OKE if you want Kubernetes) |
| LLM | **OCI Generative AI** (Cohere/Llama), add an `OCIProvider`, or call an external LLM API |
| Store | **Autonomous Database** (use the Postgres store via the Postgres-compatible endpoint, or Oracle client) |
| Secrets | OCI Vault |
| Async | OCI Queue / Streaming → `/internal/run-reading` |
| Tiered quota (managed) | **API Gateway** with usage plans |

OCI's Always Free tier (Autonomous DB + Ampere compute) and low egress make it
attractive for cost. You'll likely use the `PostgresStore` against Autonomous DB
or a managed Postgres.

---

## What stays the same everywhere

- The container, the four-stage pipeline, the anti-slop prompt + citation
  validation, the tier definitions, the cache keys.
- You implement **one** store class (`FirestoreStore` / `DynamoStore` /
  `CosmosStore` / `PostgresStore`) with the ~9 methods already defined on
  `Store` in `app/billing.py`.
- You add **one** provider class if you want a cloud-native LLM, matching the
  `Provider` interface in `app/llm.py`.

Managed API gateways (AWS usage plans, Azure APIM products, OCI API Gateway) are
the lowest-effort way to enforce and *sell* tiers, if you use one, you can lean
on it for rate/quota and keep the app's metering for analytics only.
