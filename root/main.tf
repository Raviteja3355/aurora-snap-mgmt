terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.0"
    }
  }
}

provider "aws" {
  region = var.region
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------
# NAMING CONVENTION
# All resource names follow: {client}-{env}-{base-name}
# e.g. uniuni-dev-snapshot-discovery, uniuni-prod-rds-export-role
# ---------------------------------------------------------
locals {
  name_prefix          = "${var.client}-${var.env}"
  resolved_kms_key_arn = var.kms_key_arn != "" ? var.kms_key_arn : module.kms_key[0].key_arn

  bucket_name                = "${local.name_prefix}-${var.bucket_name}"
  kms_key_alias              = "${local.name_prefix}-${var.kms_key_alias}"
  rds_export_role_name       = "${local.name_prefix}-${var.rds_export_role_name}"
  processed_tasks_table_name = "${local.name_prefix}-${var.processed_tasks_table_name}"
  discovery_lambda_role_name = "${local.name_prefix}-${var.discovery_lambda_role_name}"
  export_lambda_role_name    = "${local.name_prefix}-${var.export_lambda_role_name}"
  status_lambda_role_name    = "${local.name_prefix}-${var.status_lambda_role_name}"
  cleanup_lambda_role_name   = "${local.name_prefix}-${var.cleanup_lambda_role_name}"
  discovery_lambda_name      = "${local.name_prefix}-${var.discovery_lambda_name}"
  export_lambda_name         = "${local.name_prefix}-${var.export_lambda_name}"
  status_lambda_name         = "${local.name_prefix}-${var.status_lambda_name}"
  cleanup_lambda_name        = "${local.name_prefix}-${var.cleanup_lambda_name}"
  discovery_schedule_name    = "${local.name_prefix}-${var.discovery_schedule_name}"
  status_schedule_name       = "${local.name_prefix}-${var.status_schedule_name}"

  # Common tags applied to every taggable resource.
  # created_by   — ARN of the IAM user/role running terraform apply.
  # created_date — date of first apply; use lifecycle ignore_changes on tags
  #                if you do not want this updated on subsequent applies.
  common_tags = {
    client          = var.client
    env             = var.env
    creator         = var.creator
    created_by      = data.aws_caller_identity.current.arn
    created_by_name = element(split("/", data.aws_caller_identity.current.arn), length(split("/", data.aws_caller_identity.current.arn)) - 1)
    created_date    = formatdate("YYYY-MM-DD", timestamp())
  }
}

# ---------------------------------------------------------
# KMS KEY — created when kms_key_arn is not provided
# Pass kms_key_arn to skip creation and use an existing key.
# ---------------------------------------------------------
module "kms_key" {
  count  = var.kms_key_arn == "" ? 1 : 0
  source = "../modules/rds_snapshot_infra/kms_key"

  description             = var.kms_key_description
  alias_name              = local.kms_key_alias
  deletion_window_in_days = var.kms_key_deletion_window_in_days
  enable_key_rotation     = var.kms_key_enable_rotation
  tags                    = local.common_tags
}

# ---------------------------------------------------------
# S3 BUCKET
# ---------------------------------------------------------
module "archive_bucket" {
  source            = "../modules/rds_snapshot_infra/s3_bucket"
  bucket_name       = local.bucket_name
  kms_key_arn       = local.resolved_kms_key_arn
  deep_archive_days = var.deep_archive_days
  tags              = local.common_tags
}

# ---------------------------------------------------------
# RDS EXPORT ROLE
# ---------------------------------------------------------
module "rds_export_role" {
  source        = "../modules/rds_snapshot_infra/iam_rds_export_role"
  role_name     = local.rds_export_role_name
  s3_bucket_arn = module.archive_bucket.bucket_arn
  kms_key_arn   = local.resolved_kms_key_arn
  tags          = local.common_tags
}

# ---------------------------------------------------------
# KMS KEY POLICY
# Applied after all IAM roles exist so each role ARN can be
# named as a principal. Uses iam_policies/kms_key_policy.json.tpl.
# Only created when this module manages the KMS key.
# ---------------------------------------------------------
resource "aws_kms_key_policy" "main" {
  count  = var.kms_key_arn == "" ? 1 : 0
  key_id = module.kms_key[0].key_id
  policy = templatefile("${path.module}/../modules/rds_snapshot_infra/iam_policies/kms_key_policy.json.tpl", {
    account_id             = data.aws_caller_identity.current.account_id
    region                 = var.region
    rds_export_role_arn    = module.rds_export_role.role_arn
    export_lambda_role_arn = module.export_lambda_role.role_arn
    status_lambda_role_arn = module.status_lambda_role.role_arn
  })
}

# ---------------------------------------------------------
# DYNAMODB — processed task state tracking
# ---------------------------------------------------------
module "processed_tasks_table" {
  source        = "../modules/rds_snapshot_infra/dynamodb_table"
  table_name    = local.processed_tasks_table_name
  billing_mode  = var.dynamodb_billing_mode
  hash_key      = var.dynamodb_hash_key
  ttl_attribute = var.dynamodb_ttl_attribute
  tags          = local.common_tags
}

# ---------------------------------------------------------
# SQS DEAD-LETTER QUEUE — export lambda async failures
# ---------------------------------------------------------
resource "aws_sqs_queue" "export_dlq" {
  name                      = "${local.export_lambda_name}-dlq"
  message_retention_seconds = var.dlq_message_retention_seconds
  tags                      = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "export_dlq_messages" {
  alarm_name          = "${local.export_lambda_name}-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  metric_name         = "NumberOfMessagesSent"
  namespace           = "AWS/SQS"
  period              = var.alarm_period
  statistic           = var.alarm_statistic
  threshold           = var.alarm_threshold
  alarm_description   = "Export lambda DLQ received messages — async invocations failed permanently after retries"
  alarm_actions       = []
  dimensions          = { QueueName = aws_sqs_queue.export_dlq.name }
  tags                = local.common_tags
}

# ---------------------------------------------------------
# LAMBDA ROLES
# ---------------------------------------------------------
module "discovery_lambda_role" {
  source    = "../modules/rds_snapshot_infra/iam_lambda_role"
  role_name = local.discovery_lambda_role_name
  tags      = local.common_tags
}

module "export_lambda_role" {
  source    = "../modules/rds_snapshot_infra/iam_lambda_role"
  role_name = local.export_lambda_role_name
  tags      = local.common_tags
}

module "status_lambda_role" {
  source    = "../modules/rds_snapshot_infra/iam_lambda_role"
  role_name = local.status_lambda_role_name
  tags      = local.common_tags
}

module "cleanup_lambda_role" {
  source    = "../modules/rds_snapshot_infra/iam_lambda_role"
  role_name = local.cleanup_lambda_role_name
  tags      = local.common_tags
}

# ---------------------------------------------------------
# LAMBDA PERMISSION POLICIES (from iam_policies/ templates)
# ---------------------------------------------------------
resource "aws_iam_role_policy" "discovery_lambda" {
  name = "${local.discovery_lambda_role_name}-policy"
  role = module.discovery_lambda_role.role_name
  policy = templatefile("${path.module}/../modules/rds_snapshot_infra/iam_policies/discovery_lambda_policy.json.tpl", {
    s3_bucket_arn = module.archive_bucket.bucket_arn
    kms_key_arn   = local.resolved_kms_key_arn
  })
}

resource "aws_iam_role_policy" "export_lambda" {
  name = "${local.export_lambda_role_name}-policy"
  role = module.export_lambda_role.role_name
  policy = templatefile("${path.module}/../modules/rds_snapshot_infra/iam_policies/export_lambda_policy.json.tpl", {
    account_id           = data.aws_caller_identity.current.account_id
    rds_export_role_name = local.rds_export_role_name
    kms_key_arn          = local.resolved_kms_key_arn
    dlq_arn              = aws_sqs_queue.export_dlq.arn
  })
}

resource "aws_iam_role_policy" "status_lambda" {
  name = "${local.status_lambda_role_name}-policy"
  role = module.status_lambda_role.role_name
  policy = templatefile("${path.module}/../modules/rds_snapshot_infra/iam_policies/status_lambda_policy.json.tpl", {
    s3_bucket_arn      = module.archive_bucket.bucket_arn
    kms_key_arn        = local.resolved_kms_key_arn
    dynamodb_table_arn = module.processed_tasks_table.table_arn
    cleanup_lambda_arn = module.cleanup_lambda.function_arn
  })
}

resource "aws_iam_role_policy" "cleanup_lambda" {
  name = "${local.cleanup_lambda_role_name}-policy"
  role = module.cleanup_lambda_role.role_name
  policy = templatefile("${path.module}/../modules/rds_snapshot_infra/iam_policies/cleanup_lambda_policy.json.tpl", {
    s3_bucket_arn = module.archive_bucket.bucket_arn
  })
}

# ---------------------------------------------------------
# EXPORT LAMBDA
# ---------------------------------------------------------
module "export_lambda" {
  source        = "../modules/rds_snapshot_infra/lambda_function"
  function_name = local.export_lambda_name
  role_arn      = module.export_lambda_role.role_arn
  handler       = var.export_lambda_handler
  source_file   = var.export_lambda_source_file
  timeout       = var.export_lambda_timeout
  memory_size   = var.export_lambda_memory_mb
  dlq_arn       = aws_sqs_queue.export_dlq.arn
  tags          = local.common_tags

  env_vars = {
    ARCHIVE_BUCKET  = module.archive_bucket.bucket_id
    EXPORT_ROLE_ARN = module.rds_export_role.role_arn
    KMS_KEY_ARN     = local.resolved_kms_key_arn
    DRY_RUN_MODE    = tostring(var.dry_run_mode)
  }
}

# ---------------------------------------------------------
# DISCOVERY LAMBDA
# ---------------------------------------------------------
module "discovery_lambda" {
  source        = "../modules/rds_snapshot_infra/lambda_function"
  function_name = local.discovery_lambda_name
  role_arn      = module.discovery_lambda_role.role_arn
  handler       = var.discovery_lambda_handler
  source_file   = var.discovery_lambda_source_file
  timeout       = var.discovery_lambda_timeout
  memory_size   = var.discovery_lambda_memory_mb
  tags          = local.common_tags

  env_vars = {
    RETENTION_DAYS             = tostring(var.retention_days)
    EXPORT_LAMBDA_ARN          = module.export_lambda.function_arn
    ARCHIVE_BUCKET             = module.archive_bucket.bucket_id
    DRY_RUN_MODE               = tostring(var.dry_run_mode)
    MAX_EXPORT_CONCURRENCY     = tostring(var.max_export_concurrency)
    TARGET_CLUSTER_IDENTIFIERS = var.target_cluster_identifiers
    SNAPSHOT_NAME_PATTERN      = var.snapshot_name_pattern
    AURORA_ONLY                = tostring(var.aurora_only)
  }
}

# ---------------------------------------------------------
# STATUS LAMBDA
# ---------------------------------------------------------
module "status_lambda" {
  source        = "../modules/rds_snapshot_infra/lambda_function"
  function_name = local.status_lambda_name
  role_arn      = module.status_lambda_role.role_arn
  handler       = var.status_lambda_handler
  source_file   = var.status_lambda_source_file
  timeout       = var.status_lambda_timeout
  memory_size   = var.status_lambda_memory_mb
  tags          = local.common_tags

  env_vars = {
    BUCKET_NAME                        = module.archive_bucket.bucket_id
    BACKUP_VAULT_NAME                  = var.backup_vault_name
    DRY_RUN_MODE                       = tostring(var.dry_run_mode)
    DELETE_SOURCE_AFTER_EXPORT         = tostring(var.delete_source_after_export)
    DELETE_DELAY_DAYS                  = tostring(var.delete_delay_days)
    EXPORT_TASK_LOOKBACK_DAYS          = tostring(var.export_task_lookback_days)
    PROCESSED_TASKS_TABLE              = module.processed_tasks_table.table_name
    TEAMS_SUCCESS_WEBHOOK_URL          = var.teams_success_webhook_url
    TEAMS_FAILURE_WEBHOOK_URL          = var.teams_failure_webhook_url
    TEAMS_PENDING_DELETION_WEBHOOK_URL = var.teams_pending_deletion_webhook_url
    TEAMS_DELETED_WEBHOOK_URL          = var.teams_deleted_webhook_url
    EXPORT_LAMBDA_ARN                  = module.export_lambda.function_arn
    CLEANUP_LAMBDA_ARN                 = module.cleanup_lambda.function_arn
    CLEANUP_DELAY_HOURS                = tostring(var.cleanup_delay_hours)
    MAX_RETRIES                        = tostring(var.max_retries)
  }
}

# ---------------------------------------------------------
# CLEANUP LAMBDA
# ---------------------------------------------------------
module "cleanup_lambda" {
  source        = "../modules/rds_snapshot_infra/lambda_function"
  function_name = local.cleanup_lambda_name
  role_arn      = module.cleanup_lambda_role.role_arn
  handler       = var.cleanup_lambda_handler
  source_file   = var.cleanup_lambda_source_file
  timeout       = var.cleanup_lambda_timeout
  memory_size   = var.cleanup_lambda_memory_mb
  tags          = local.common_tags

  env_vars = {
    BUCKET_NAME  = module.archive_bucket.bucket_id
    DRY_RUN_MODE = tostring(var.dry_run_mode)
  }
}

# ---------------------------------------------------------
# EVENTBRIDGE RULE — DISCOVERY (daily)
# ---------------------------------------------------------
module "eventbridge_discovery" {
  source              = "../modules/rds_snapshot_infra/eventbridge_rule"
  rule_name           = local.discovery_schedule_name
  schedule_expression = var.discovery_schedule_expression
  target_id           = var.discovery_schedule_target_id
  target_lambda_arn   = module.discovery_lambda.function_arn
  target_lambda_name  = module.discovery_lambda.function_name
  tags                = local.common_tags
}

# ---------------------------------------------------------
# EVENTBRIDGE RULE — STATUS CHECK (every 15 minutes)
# ---------------------------------------------------------
module "eventbridge_status" {
  source              = "../modules/rds_snapshot_infra/eventbridge_rule"
  rule_name           = local.status_schedule_name
  schedule_expression = var.status_schedule_expression
  target_id           = var.status_schedule_target_id
  target_lambda_arn   = module.status_lambda.function_arn
  target_lambda_name  = module.status_lambda.function_name
  tags                = local.common_tags
}

# ---------------------------------------------------------
# CLOUDWATCH ALARMS
# ---------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "discovery_errors" {
  alarm_name          = "${local.discovery_lambda_name}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = var.alarm_period
  statistic           = var.alarm_statistic
  threshold           = var.alarm_threshold
  alarm_description   = "Discovery lambda has errors"
  alarm_actions       = []
  dimensions          = { FunctionName = local.discovery_lambda_name }
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "export_errors" {
  alarm_name          = "${local.export_lambda_name}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = var.alarm_period
  statistic           = var.alarm_statistic
  threshold           = var.alarm_threshold
  alarm_description   = "Export lambda has errors"
  alarm_actions       = []
  dimensions          = { FunctionName = local.export_lambda_name }
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "status_errors" {
  alarm_name          = "${local.status_lambda_name}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = var.alarm_period
  statistic           = var.alarm_statistic
  threshold           = var.alarm_threshold
  alarm_description   = "Status lambda has errors"
  alarm_actions       = []
  dimensions          = { FunctionName = local.status_lambda_name }
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "export_throttles" {
  alarm_name          = "${local.export_lambda_name}-throttles"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = var.alarm_period
  statistic           = var.alarm_statistic
  threshold           = var.alarm_threshold
  alarm_description   = "Export lambda is being throttled — async invocations may be lost"
  alarm_actions       = []
  dimensions          = { FunctionName = local.export_lambda_name }
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "cleanup_errors" {
  alarm_name          = "${local.cleanup_lambda_name}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = var.alarm_period
  statistic           = var.alarm_statistic
  threshold           = var.alarm_threshold
  alarm_description   = "Cleanup lambda has errors"
  alarm_actions       = []
  dimensions          = { FunctionName = local.cleanup_lambda_name }
  tags                = local.common_tags
}
