# ---------------------------------------------------------
# OUTPUTS
# ---------------------------------------------------------
output "bucket_id"       { value = module.archive_bucket.bucket_id }
output "bucket_arn"      { value = module.archive_bucket.bucket_arn }
output "rds_export_role" { value = module.rds_export_role.role_arn }
output "kms_key_arn"     { value = local.resolved_kms_key_arn }
output "kms_key_id" {
  value = var.kms_key_arn == "" ? module.kms_key[0].key_id : null
}
output "kms_alias_arn" {
  value = var.kms_key_arn == "" ? module.kms_key[0].alias_arn : null
}
