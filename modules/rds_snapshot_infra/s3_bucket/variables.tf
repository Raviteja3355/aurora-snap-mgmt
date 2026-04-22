variable "bucket_name"       { type = string }
variable "kms_key_arn"       { type = string }
variable "deep_archive_days" { type = number }
variable "tags" {
  type    = map(string)
  default = {}
}
variable "lifecycle_prefix" {
  type        = string
  default     = "snapshots/"
  description = "S3 key prefix filter for the Deep Archive lifecycle rule"
}
variable "lifecycle_rule_id" {
  type        = string
  default     = "deep-archive"
  description = "ID for the S3 lifecycle rule"
}
variable "versioning_status" {
  type        = string
  default     = "Enabled"
  description = "S3 bucket versioning status: Enabled, Suspended, or Disabled"
}


