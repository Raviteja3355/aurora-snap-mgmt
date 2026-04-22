variable "description" {
  type        = string
  description = "Human-readable description for the KMS key"
}

variable "alias_name" {
  type        = string
  description = "KMS key alias name — do NOT include the 'alias/' prefix, it is added automatically"
}

variable "deletion_window_in_days" {
  type        = number
  default     = 30
  description = "Days to wait before permanently deleting the key after it is scheduled for deletion"
}

variable "enable_key_rotation" {
  type        = bool
  default     = true
  description = "Enable automatic annual key rotation"
}

variable "tags" {
  type    = map(string)
  default = {}
}
