# Creates the IAM role with a lambda trust policy loaded from the shared policy file.
# All permission policies are attached in the parent module (main.tf) via
# aws_iam_role_policy resources that use templatefile() to load per-lambda
# policy documents from modules/rds_snapshot_infra/iam_policies/.
resource "aws_iam_role" "role" {
  name               = var.role_name
  assume_role_policy = file("${path.module}/../iam_policies/lambda_trust_policy.json")
  tags               = var.tags
}
