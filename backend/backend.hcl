# =============================================================================
# BACKEND CONFIG — centralised S3 remote-state and tfvars bucket settings.
# Read by the root terragrunt.hcl via read_terragrunt_config().
# Change bucket / region here; no other file needs updating.
# =============================================================================

locals {
  state_bucket  = "aurora-snap-mgmt-tfstate-320042238069"
  state_region  = "ap-south-1"
  config_bucket = "aurora-snap-mgmt-tfstate-320042238069"
  config_prefix = "config"
}
