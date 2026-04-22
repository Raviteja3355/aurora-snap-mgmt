# Aurora Snapshot Export & Cleanup Automation

Automates the discovery, export, monitoring, and cleanup of Amazon RDS / Aurora snapshot exports to S3. Infrastructure is managed with Terraform + Terragrunt using a single configuration file for all environments.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Terragrunt Configuration](#terragrunt-configuration)
- [Backend Configuration](#backend-configuration)
- [tfvars Management](#tfvars-management)
- [Deploying](#deploying)
- [Terragrunt Commands](#terragrunt-commands)
- [Lambda Functions](#lambda-functions)
- [IAM Roles and Policies](#iam-roles-and-policies)
- [KMS Encryption](#kms-encryption)
- [Resource Tagging](#resource-tagging)
- [Destroying Infrastructure](#destroying-infrastructure)

---

## How It Works

```
EventBridge (daily)
      │
      ▼
Discovery Lambda
  - Lists all RDS / Aurora snapshots
  - Filters by cluster identifiers and name pattern (if configured)
  - Skips snapshots already exported (checks DynamoDB)
  - Invokes Export Lambda for each eligible snapshot
      │
      ▼
Export Lambda
  - Starts an RDS export task to S3 (encrypted with KMS)
  - Async failures land in SQS Dead-Letter Queue
  - CloudWatch Alarm fires if DLQ receives messages
      │
      ▼
EventBridge (every 15 min)
      │
      ▼
Status Lambda
  - Polls in-progress export tasks
  - On COMPLETE  → sends success notification (Teams)
  - On FAILED    → retries up to max_retries; on final failure invokes Cleanup Lambda
  - After delay  → optionally deletes source snapshot
  - Records completed tasks in DynamoDB (prevents re-export)
      │
      ▼
Cleanup Lambda
  - Deletes failed export data from S3
  - Sends deletion notification (Teams)
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          AWS Account                            │
│                                                                 │
│  EventBridge (daily) ──► Discovery Lambda                       │
│                               │                                 │
│                               ▼                                 │
│                         Export Lambda ──► RDS Export Task       │
│                               │               │                 │
│                               ▼               ▼                 │
│                           SQS DLQ       S3 Bucket (KMS)         │
│                               │               │                 │
│  EventBridge (15 min) ──► Status Lambda ◄─────┘                 │
│                               │                                 │
│                               ├──► DynamoDB (task tracking)     │
│                               ├──► Cleanup Lambda               │
│                               └──► Notifications (Teams)        │
│                                                                 │
│  KMS Key ──────────────────────────────────────────────────────►│
│  (encrypts S3 objects and RDS exports)                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
snapshot-export/
│
├── terragrunt.hcl                    # Single Terragrunt config for all environments
│
├── backend/
│   └── backend.hcl                   # S3 state bucket + tfvars bucket settings
│
├── root/                             # Terraform root module
│   ├── main.tf                       # Orchestrates all modules
│   ├── variables.tf                  # All input variable declarations
│   └── outputs.tf                    # Exported values (bucket ARN, lambda ARNs, etc.)
│
├── modules/
│   └── rds_snapshot_infra/           # Reusable Terraform submodules
│       ├── s3_bucket/                # S3 bucket with lifecycle + encryption
│       ├── kms_key/                  # KMS key + alias (used when no existing key provided)
│       ├── dynamodb_table/           # DynamoDB task-tracking table
│       ├── lambda_function/          # Lambda function + ZIP packaging
│       ├── eventbridge_rule/         # EventBridge schedule + Lambda target
│       ├── iam_lambda_role/          # IAM execution role for Lambda functions
│       ├── iam_rds_export_role/      # IAM role assumed by RDS export service
│       └── iam_policies/             # JSON policy templates (.json / .json.tpl)
│
└── lambdas/                          # Lambda Python source files
    ├── discovery_lambda.py
    ├── export_lambda.py
    ├── status_lambda.py
    └── cleanup_lambda.py
```

---

## Prerequisites

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| [Terraform](https://developer.hashicorp.com/terraform/downloads) | >= 1.5 | Infrastructure provisioning |
| [Terragrunt](https://terragrunt.gruntwork.io/docs/getting-started/install/) | >= 0.50 | Environment wrapper |
| [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) | >= 2.0 | AWS authentication + S3 tfvars download |

### Configure AWS credentials

```bash
# Named profile
aws configure --profile my-profile
export AWS_PROFILE=my-profile          # Git Bash / Linux / macOS
$env:AWS_PROFILE="my-profile"          # PowerShell

# Verify
aws sts get-caller-identity
```

---

## Terragrunt Configuration

There is a **single `terragrunt.hcl`** at the repo root — no per-environment HCL files. It handles everything: remote state, tfvars download/cleanup, and Lambda source paths.

### How it works

| Responsibility | Mechanism |
|----------------|-----------|
| Environment selection | `TG_ENV` env var read via `get_env("TG_ENV")` |
| Backend settings | `read_terragrunt_config("backend/backend.hcl")` |
| Remote state | S3 bucket + key `environments/<env>/terraform.tfstate` |
| tfvars download | `before_hook` — runs `aws s3 cp` before every plan/apply/destroy |
| tfvars cleanup | `after_hook` — deletes local copy after apply/destroy |
| Lambda source paths | Passed as `inputs` using `get_repo_root()` |

### Key sections

```hcl
locals {
  backend      = read_terragrunt_config("${get_repo_root()}/backend/backend.hcl")
  env          = get_env("TG_ENV")                          # set inline: TG_ENV=qa
  tfvars_s3    = "s3://<config_bucket>/config/<env>.tfvars" # source in S3
  tfvars_local = "${get_repo_root()}/.tfvars-cache/<env>.tfvars" # temp download path
}
```

- **`before_hook`** — downloads `<env>.tfvars` from S3 into `.tfvars-cache/` before every plan/apply/destroy
- **`after_hook`** — deletes the local copy after apply/destroy (prevents stale secrets on disk)
- **`extra_arguments`** — passes the downloaded tfvars file to every Terraform command automatically
- **`inputs`** — injects Lambda source file paths so Terraform always uses the correct `.py` files from the repo

---

## Backend Configuration

All backend settings are centralised in `backend/backend.hcl`. This is the **only file** you need to update when switching between environments.

```
backend/backend.hcl
  └── state_bucket   → S3 bucket for Terraform state files
  └── state_region   → AWS region of the state bucket
  └── config_bucket  → S3 bucket where tfvars are stored
  └── config_prefix  → Folder prefix inside the config bucket
```

```hcl
locals {
  state_bucket  = "terraform-state-external-collaboration-uniuni-com"
  state_region  = "us-west-2"
  config_bucket = "terraform-config-external-collaboration-uniuni-com"
  config_prefix = "config"
}
```

---

## tfvars Management

Environment-specific variables are stored in S3 — there are no local tfvars files committed to git.

### S3 layout

```
s3://<config_bucket>/
└── config/
    ├── qa.tfvars
    └── prod.tfvars
```

### Upload tfvars to S3 (once, or on every change)

```bash
aws s3 cp qa.tfvars   s3://<config_bucket>/config/qa.tfvars
aws s3 cp prod.tfvars s3://<config_bucket>/config/prod.tfvars
```

### Lifecycle during plan / apply / destroy

```
terragrunt plan / apply / destroy
  ↓  before_hook  → downloads <env>.tfvars from S3 into .tfvars-cache/
  ↓  terraform    → runs using .tfvars-cache/<env>.tfvars
  ↓  after_hook   → deletes .tfvars-cache/<env>.tfvars   (apply / destroy only)
```

The downloaded tfvars file is temporary and gitignored. S3 is the permanent source of truth.

---

## Deploying

All commands run from the **repo root**. Set `TG_ENV` inline to select the environment.

### Windows PowerShell

```powershell
# Plan
$env:TG_ENV="qa"; terragrunt plan

# Apply
$env:TG_ENV="qa"; terragrunt apply

# Destroy
$env:TG_ENV="qa"; terragrunt destroy
```

### Git Bash / Linux / macOS

```bash
TG_ENV=qa terragrunt plan
TG_ENV=qa terragrunt apply
TG_ENV=qa terragrunt destroy
```

### First-time initialisation (or after backend change)

```powershell
$env:TG_ENV="qa"; terragrunt init -reconfigure
```

### Environment summary

| TG_ENV | Account | Region | KMS Key |
|--------|---------|--------|---------|
| `qa` | `791894688590` | `us-west-2` | `650996eb-a059-4246-b34f-6f174cae82de` |
| `prod` | `791894688590` | `us-west-2` | `650996eb-a059-4246-b34f-6f174cae82de` |

---

## Terragrunt Commands

```powershell
# Preview changes
$env:TG_ENV="qa"; terragrunt plan

# Apply changes
$env:TG_ENV="qa"; terragrunt apply

# Apply without confirmation prompt
$env:TG_ENV="qa"; terragrunt apply --auto-approve

# List all resources in state
$env:TG_ENV="qa"; terragrunt state list

# Inspect a specific resource
$env:TG_ENV="qa"; terragrunt state show module.archive_bucket.aws_s3_bucket.s3

# Remove a resource from state without destroying it
$env:TG_ENV="qa"; terragrunt state rm 'module.kms_key[0].aws_kms_alias.alias'

# Show all outputs
$env:TG_ENV="qa"; terragrunt output

# Destroy all resources
$env:TG_ENV="qa"; terragrunt destroy
```

---

## Lambda Functions

### Discovery Lambda (`lambdas/discovery_lambda.py`)
Triggered daily by EventBridge. Lists snapshots, checks DynamoDB for already-exported ones, invokes Export Lambda for eligible snapshots.

### Export Lambda (`lambdas/export_lambda.py`)
Starts an RDS export task to S3 encrypted with KMS. Async failures are routed to the SQS DLQ.

### Status Lambda (`lambdas/status_lambda.py`)
Triggered every 15 minutes by EventBridge. Monitors export task status, handles retries, sends Teams notifications, optionally deletes source snapshots, records results in DynamoDB.

### Cleanup Lambda (`lambdas/cleanup_lambda.py`)
Invoked by Status Lambda after final export failure. Removes failed export data from S3.

---

## IAM Roles and Policies

| Role | Purpose | Policy Template |
|------|---------|----------------|
| RDS Export Role | Assumed by RDS to write exports to S3 | `rds_export_role_policy.json.tpl` |
| Discovery Lambda Role | Describe snapshots, invoke Export Lambda | `discovery_lambda_policy.json.tpl` |
| Export Lambda Role | Start export tasks, pass RDS role, write to DLQ | `export_lambda_policy.json.tpl` |
| Status Lambda Role | Describe/delete snapshots, read S3, write DynamoDB | `status_lambda_policy.json.tpl` |
| Cleanup Lambda Role | List and delete S3 objects | `cleanup_lambda_policy.json.tpl` |

Trust policies are in `modules/rds_snapshot_infra/iam_policies/`:
- `lambda_trust_policy.json` — for all Lambda roles
- `rds_export_trust_policy.json` — for the RDS export role

---

## KMS Encryption

Set `kms_key_arn` in your tfvars to use an **existing** key — no new key will be created.

Leave `kms_key_arn` empty to let Terraform create and manage a new KMS key automatically.

The key encrypts:
- All objects in the S3 export bucket
- RDS export tasks in transit

---

## Resource Tagging

Every taggable resource receives these tags automatically:

| Tag Key | Value |
|---------|-------|
| `client` | Value of `client` variable in tfvars |
| `env` | Value of `env` variable in tfvars |
| `creator` | Value of `creator` variable in tfvars |
| `created_by` | Full IAM caller ARN at apply time |
| `created_by_name` | IAM username extracted from the ARN |
| `created_date` | Date of apply (`YYYY-MM-DD`) |

----

## Destroying Infrastructure

```powershell
$env:TG_ENV="qa"; terragrunt destroy
```

> **Warning:** This deletes all Lambda functions, IAM roles, DynamoDB table, SQS queue, CloudWatch alarms, and schedules. The S3 bucket will fail to destroy if it contains exported snapshot data — empty it first. The KMS key enters a scheduled deletion window (default 30 days) and can be cancelled within that period.
