resource "aws_iam_role" "role" {
  name               = var.role_name
  assume_role_policy = file("${path.module}/../iam_policies/rds_export_trust_policy.json")
  tags               = var.tags
}

resource "aws_iam_policy" "policy" {
  name = "${var.role_name}-policy"
  policy = templatefile("${path.module}/../iam_policies/rds_export_role_policy.json.tpl", {
    s3_bucket_arn = var.s3_bucket_arn
    kms_key_arn   = var.kms_key_arn
  })
}

resource "aws_iam_role_policy_attachment" "attach" {
  role       = aws_iam_role.role.name
  policy_arn = aws_iam_policy.policy.arn
}
