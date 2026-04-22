# Key policy is managed by aws_kms_key_policy in the parent module (main.tf).
# That resource runs after all IAM roles are created so it can name each role ARN
# as a principal — avoiding a circular dependency with iam_rds_export_role and
# the lambda role modules.
resource "aws_kms_key" "key" {
  description             = var.description
  deletion_window_in_days = var.deletion_window_in_days
  enable_key_rotation     = var.enable_key_rotation
  tags                    = var.tags
}

resource "aws_kms_alias" "alias" {
  name          = "alias/${var.alias_name}"
  target_key_id = aws_kms_key.key.key_id
}
