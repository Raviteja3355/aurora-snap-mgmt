# -----------------------------
# Global Settings
# -----------------------------
variable "client" {
  type        = string
  description = "Client or project name — used as the first segment of the resource naming prefix {client}-{env}"
}

variable "creator" {
  type        = string
  description = "Tag value identifying the team or organisation that owns these resources"
}

variable "env" {
  type        = string
  description = "Environment name (dev, qa, test, prod) — used in the resource naming prefix {client}-{env}"
}

variable "region" {
  type        = string
  description = "AWS region to deploy resources"
}

variable "dry_run_mode" {
  type        = bool
  default     = false
  description = "When true, all lambdas log intended actions without making changes"
}

variable "max_export_concurrency" {
  type        = number
  default     = 5
  description = "Maximum concurrent export tasks across all runs (checked against in-progress tasks)"
}

variable "target_cluster_identifiers" {
  type        = string
  default     = ""
  description = "Comma-separated DB instance/cluster identifiers to target; empty = all"
}

variable "snapshot_name_pattern" {
  type        = string
  default     = ""
  description = "Regex pattern matched against snapshot identifier; empty = all"
}

variable "aurora_only" {
  type        = bool
  default     = false
  description = "When true, discovery only processes Aurora cluster snapshots and skips RDS instance snapshots"
}

variable "delete_source_after_export" {
  type        = bool
  default     = false
  description = "When true, source snapshots are deleted after successful export and delay"
}

variable "delete_delay_days" {
  type        = number
  default     = 7
  description = "Days to wait after export completion before deleting the source snapshot"
}

variable "teams_success_webhook_url" {
  type        = string
  default     = ""
  description = "Microsoft Teams webhook URL for the success channel; empty = disabled"
}

variable "teams_failure_webhook_url" {
  type        = string
  default     = ""
  description = "Microsoft Teams webhook URL for the failure channel; empty = disabled"
}

variable "teams_pending_deletion_webhook_url" {
  type        = string
  default     = ""
  description = "Microsoft Teams webhook URL for the pending-deletion channel; empty = disabled"
}

variable "teams_deleted_webhook_url" {
  type        = string
  default     = ""
  description = "Microsoft Teams webhook URL for the deleted channel; empty = disabled"
}

variable "max_retries" {
  type        = number
  default     = 5
  description = "Maximum number of export retry attempts for FAILED, CANCELED, or INTEGRITY_FAILED tasks"
}

variable "cleanup_delay_hours" {
  type        = number
  default     = 1
  description = "Hours to wait after final failure before invoking the cleanup lambda"
}

variable "processed_tasks_table_name" {
  type        = string
  description = "DynamoDB table name for tracking processed export tasks"
}

variable "backup_vault_name" {
  type        = string
  default     = ""
  description = "AWS Backup Vault name; leave empty when using manual snapshots"
}

variable "export_task_lookback_days" {
  type        = number
  default     = 90
  description = "Status lambda only scans export tasks started within this many days"
}

# -----------------------------
# S3 / Storage
# -----------------------------
variable "bucket_name" {
  type        = string
  description = "Name of the S3 bucket for snapshot exports"
}

variable "deep_archive_days" {
  type        = number
  description = "Number of days before moving objects to Deep Archive"
}

variable "retention_days" {
  type        = number
  description = "Retention period (days); snapshots older than this are eligible for export"
}

# -----------------------------
# KMS Key
# -----------------------------
variable "kms_key_arn" {
  type        = string
  default     = ""
  description = "ARN of an existing KMS key to use. Leave empty to create a new key."
}

variable "kms_key_alias" {
  type        = string
  default     = ""
  description = "Alias for the created KMS key (without 'alias/' prefix). Required when kms_key_arn is empty."
}

variable "kms_key_description" {
  type        = string
  default     = "KMS key for RDS snapshot exports and S3 encryption"
  description = "Description for the created KMS key"
}

variable "kms_key_deletion_window_in_days" {
  type        = number
  default     = 30
  description = "Days to wait before permanently deleting the key after scheduled deletion"
}

variable "kms_key_enable_rotation" {
  type        = bool
  default     = true
  description = "Enable automatic annual KMS key rotation"
}

# -----------------------------
# IAM Role Names
# -----------------------------
variable "rds_export_role_name" {
  type        = string
  description = "IAM role name for RDS export"
}

variable "discovery_lambda_role_name" {
  type        = string
  description = "IAM role name for discovery lambda"
}

variable "export_lambda_role_name" {
  type        = string
  description = "IAM role name for export lambda"
}

variable "status_lambda_role_name" {
  type        = string
  description = "IAM role name for status lambda"
}

variable "cleanup_lambda_role_name" {
  type        = string
  description = "IAM role name for cleanup lambda"
}

# -----------------------------
# Lambda Function Names
# -----------------------------
variable "discovery_lambda_name" {
  type        = string
  description = "Name of the discovery lambda function"
}

variable "export_lambda_name" {
  type        = string
  description = "Name of the export lambda function"
}

variable "status_lambda_name" {
  type        = string
  description = "Name of the status lambda function"
}

variable "cleanup_lambda_name" {
  type        = string
  description = "Name of the cleanup lambda function"
}

# -----------------------------
# Lambda Handlers
# -----------------------------
variable "discovery_lambda_handler" {
  type        = string
  description = "Handler for discovery lambda"
}

variable "export_lambda_handler" {
  type        = string
  description = "Handler for export lambda"
}

variable "status_lambda_handler" {
  type        = string
  description = "Handler for status lambda"
}

variable "cleanup_lambda_handler" {
  type        = string
  default     = "cleanup_lambda.handler"
  description = "Handler for cleanup lambda"
}

# -----------------------------
# Lambda Source Files
# -----------------------------
variable "discovery_lambda_source_file" {
  type        = string
  description = "Path to discovery lambda Python source file"
}

variable "export_lambda_source_file" {
  type        = string
  description = "Path to export lambda Python source file"
}

variable "status_lambda_source_file" {
  type        = string
  description = "Path to status lambda Python source file"
}

variable "cleanup_lambda_source_file" {
  type        = string
  description = "Path to cleanup lambda Python source file"
}

# -----------------------------
# Lambda Timeouts (seconds)
# -----------------------------
variable "discovery_lambda_timeout" {
  type        = number
  default     = 120
  description = "Timeout for discovery lambda in seconds"
}

variable "export_lambda_timeout" {
  type        = number
  default     = 60
  description = "Timeout for export lambda in seconds"
}

variable "status_lambda_timeout" {
  type        = number
  default     = 300
  description = "Timeout for status lambda in seconds"
}

variable "cleanup_lambda_timeout" {
  type        = number
  default     = 120
  description = "Timeout for cleanup lambda in seconds"
}

# -----------------------------
# Lambda Memory (MB)
# -----------------------------
variable "discovery_lambda_memory_mb" {
  type        = number
  default     = 256
  description = "Memory for discovery lambda in MB"
}

variable "export_lambda_memory_mb" {
  type        = number
  default     = 256
  description = "Memory for export lambda in MB"
}

variable "status_lambda_memory_mb" {
  type        = number
  default     = 256
  description = "Memory for status lambda in MB"
}

variable "cleanup_lambda_memory_mb" {
  type        = number
  default     = 128
  description = "Memory for cleanup lambda in MB"
}

# -----------------------------
# DynamoDB
# -----------------------------
variable "dynamodb_billing_mode" {
  type        = string
  default     = "PAY_PER_REQUEST"
  description = "Billing mode for the processed tasks DynamoDB table"
}

variable "dynamodb_hash_key" {
  type        = string
  default     = "task_id"
  description = "Hash key attribute name for the processed tasks DynamoDB table"
}

variable "dynamodb_ttl_attribute" {
  type        = string
  default     = "ttl"
  description = "TTL attribute name for the processed tasks DynamoDB table"
}

# -----------------------------
# CloudWatch Alarms
# -----------------------------
variable "alarm_evaluation_periods" {
  type        = number
  default     = 1
  description = "Number of evaluation periods for all CloudWatch metric alarms"
}

variable "alarm_period" {
  type        = number
  default     = 300
  description = "Evaluation period in seconds for all CloudWatch metric alarms"
}

variable "alarm_statistic" {
  type        = string
  default     = "Sum"
  description = "Statistic to use for all CloudWatch metric alarms"
}

variable "alarm_threshold" {
  type        = number
  default     = 0
  description = "Threshold value for all CloudWatch metric alarms"
}

# -----------------------------
# SQS DLQ
# -----------------------------
variable "dlq_message_retention_seconds" {
  type        = number
  default     = 1209600
  description = "Message retention period in seconds for the export lambda DLQ (default: 14 days)"
}

# -----------------------------
# EventBridge Schedules
# -----------------------------
variable "discovery_schedule_name" {
  type        = string
  description = "EventBridge rule name for discovery lambda"
}

variable "discovery_schedule_expression" {
  type        = string
  description = "Schedule expression for discovery lambda"
}

variable "discovery_schedule_target_id" {
  type        = string
  description = "Target ID for discovery lambda schedule"
}

variable "status_schedule_name" {
  type        = string
  description = "EventBridge rule name for status lambda"
}

variable "status_schedule_expression" {
  type        = string
  description = "Schedule expression for status lambda"
}

variable "status_schedule_target_id" {
  type        = string
  description = "Target ID for status lambda schedule"
}
