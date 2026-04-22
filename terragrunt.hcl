# =============================================================================
# SINGLE TERRAGRUNT CONFIG — one file for all environments.
#
# Set TG_ENV before every command to select the environment:
#
#   Linux / macOS / Git Bash:
#     TG_ENV=qa   terragrunt plan
#     TG_ENV=prod terragrunt apply
#
#   Windows PowerShell:
#     $env:TG_ENV="qa";   terragrunt plan
#     $env:TG_ENV="prod"; terragrunt apply
#
# tfvars are downloaded from S3 automatically before every plan/apply/destroy.
# To update tfvars, edit environments/<env>.tfvars then upload:
#   aws s3 cp environments/qa.tfvars   s3://<bucket>/config/qa.tfvars
#   aws s3 cp environments/prod.tfvars s3://<bucket>/config/prod.tfvars
# =============================================================================

locals {
  backend      = read_terragrunt_config("${get_repo_root()}/backend/backend.hcl")
  env          = get_env("TG_ENV")
  tfvars_s3    = "s3://${local.backend.locals.config_bucket}/${local.backend.locals.config_prefix}/${local.env}.tfvars"
  tfvars_local = "${get_repo_root()}/.tfvars-cache/${local.env}.tfvars"
}

remote_state {
  backend = "s3"

  generate = {
    path      = "backend.tf"
    if_exists = "overwrite_terragrunt"
  }

  config = {
    bucket  = local.backend.locals.state_bucket
    region  = local.backend.locals.state_region
    encrypt = true
    key     = "environments/${local.env}/terraform.tfstate"
  }
}

terraform {
  source = "${get_repo_root()}//root"

  before_hook "download_tfvars" {
    commands = get_terraform_commands_that_need_vars()
    execute  = ["aws", "s3", "cp", local.tfvars_s3, local.tfvars_local]
  }

  after_hook "delete_tfvars" {
    commands     = ["apply", "destroy"]
    execute      = ["sh", "-c", "rm -f '${local.tfvars_local}'"]
    run_on_error = true
  }

  extra_arguments "var_files" {
    commands           = get_terraform_commands_that_need_vars()
    required_var_files = [local.tfvars_local]
  }
}

inputs = {
  discovery_lambda_source_file = "${get_repo_root()}/lambdas/discovery_lambda.py"
  export_lambda_source_file    = "${get_repo_root()}/lambdas/export_lambda.py"
  status_lambda_source_file    = "${get_repo_root()}/lambdas/status_lambda.py"
  cleanup_lambda_source_file   = "${get_repo_root()}/lambdas/cleanup_lambda.py"
}
