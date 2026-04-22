variable "role_name"     { type = string }
variable "s3_bucket_arn" { type = string }
variable "kms_key_arn" {
  type        = string
  description = "ARN of the KMS key used to encrypt RDS exports and S3 objects"
}
variable "tags" {
  type    = map(string)
  default = {}
}
