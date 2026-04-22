output "key_arn"   { value = aws_kms_key.key.arn }
output "key_id"    { value = aws_kms_key.key.key_id }
output "alias_arn" { value = aws_kms_alias.alias.arn }
