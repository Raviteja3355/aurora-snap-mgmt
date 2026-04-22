# =============================================================================
# qa ENVIRONMENT — (account: 320042238069, region: ap-south-1)
# Upload to S3 then delete local copy:
#   aws s3 cp environments/qa.tfvars s3://aurora-snap-mgmt-tfstate-320042238069/config/qa.tfvars
# Run:
#   $env:TG_ENV="qa"; terragrunt plan
# =============================================================================

# --- Client / Project ---
client  = "uniuni"
env     = "qa"
creator = "Mediamint-Databeat"
region  = "ap-south-1"

# --- Core Infrastructure ---
bucket_name       = "uni-ext-collab-qa-snapshot-exports"
kms_key_arn       = "arn:aws:kms:ap-south-1:320042238069:key/60b3af54-2c60-4350-a529-c248803f2dcb"
kms_key_alias     = "uni-ext-collab-qa-snapshot-kms"
retention_days    = 0
deep_archive_days = 1

# --- Behaviour Flags ---
dry_run_mode               = true
delete_source_after_export = false
delete_delay_days          = 1
aurora_only                = true
target_cluster_identifiers = ""
snapshot_name_pattern      = ""

# --- Export Settings ---
max_export_concurrency     = 2
max_retries                = 1
cleanup_delay_hours        = 1
export_task_lookback_days  = 7
backup_vault_name          = ""
processed_tasks_table_name = "uni-ext-collab-qa-snapshot-processed-tasks"

# --- IAM Role Names ---
rds_export_role_name       = "uni-ext-collab-qa-rds-export-role"
discovery_lambda_role_name = "uni-ext-collab-qa-discovery-lambda-role"
export_lambda_role_name    = "uni-ext-collab-qa-export-lambda-role"
status_lambda_role_name    = "uni-ext-collab-qa-status-lambda-role"
cleanup_lambda_role_name   = "uni-ext-collab-qa-cleanup-lambda-role"

# --- Lambda Names ---
discovery_lambda_name = "uni-ext-collab-qa-snapshot-discovery"
export_lambda_name    = "uni-ext-collab-qa-snapshot-export"
status_lambda_name    = "uni-ext-collab-qa-snapshot-status"
cleanup_lambda_name   = "uni-ext-collab-qa-snapshot-cleanup"

# --- Lambda Handlers ---
discovery_lambda_handler = "discovery_lambda.handler"
export_lambda_handler    = "export_lambda.handler"
status_lambda_handler    = "status_lambda.handler"
cleanup_lambda_handler   = "cleanup_lambda.handler"

# --- Lambda Timeouts (seconds) ---
discovery_lambda_timeout = 120
export_lambda_timeout    = 60
status_lambda_timeout    = 300
cleanup_lambda_timeout   = 120

# --- Lambda Memory (MB) ---
discovery_lambda_memory_mb = 256
export_lambda_memory_mb    = 256
status_lambda_memory_mb    = 256
cleanup_lambda_memory_mb   = 128

# --- EventBridge Schedules ---
discovery_schedule_name       = "uni-ext-collab-qa-snapshot-discovery-schedule"
discovery_schedule_expression = "cron(0 2 * * ? *)"
discovery_schedule_target_id  = "uni-ext-collab-qa-discovery-target"
status_schedule_name          = "uni-ext-collab-qa-snapshot-status-schedule"
status_schedule_expression    = "rate(15 minutes)"
status_schedule_target_id     = "uni-ext-collab-qa-status-target"

# --- Notifications (leave empty to disable) ---
teams_success_webhook_url          = ""
teams_failure_webhook_url          = ""
teams_pending_deletion_webhook_url = ""
teams_deleted_webhook_url          = ""
