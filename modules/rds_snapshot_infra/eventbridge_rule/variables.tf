variable "rule_name"           { type = string }
variable "schedule_expression" { type = string }
variable "target_id"           { type = string }
variable "target_lambda_arn"   { type = string }
variable "target_lambda_name"  { type = string }
variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags to apply to the EventBridge rule"
}
