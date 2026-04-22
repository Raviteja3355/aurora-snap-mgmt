resource "aws_dynamodb_table" "dynamodb" {
  name         = var.table_name
  billing_mode = var.billing_mode
  hash_key     = var.hash_key

  attribute {
    name = var.hash_key
    type = "S"
  }

  ttl {
    attribute_name = var.ttl_attribute
    enabled        = true
  }

  tags = merge({ Name = var.table_name }, var.tags)
}
