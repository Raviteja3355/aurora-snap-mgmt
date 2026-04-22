variable "table_name" {
  type        = string
  description = "DynamoDB table name"
}

variable "billing_mode" {
  type        = string
  default     = "PAY_PER_REQUEST"
  description = "Billing mode for the DynamoDB table"
}

variable "hash_key" {
  type        = string
  default     = "task_id"
  description = "Hash key attribute name"
}

variable "ttl_attribute" {
  type        = string
  default     = "ttl"
  description = "TTL attribute name"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags to apply to the DynamoDB table"
}
