resource "aws_s3_bucket" "s3" {
  bucket = var.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "block" {
  bucket = aws_s3_bucket.s3.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "versioning" {
  bucket = aws_s3_bucket.s3.id
  versioning_configuration { status = var.versioning_status }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sse" {
  bucket = aws_s3_bucket.s3.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "lifecycle" {
  bucket = aws_s3_bucket.s3.id
  rule {
    id     = var.lifecycle_rule_id
    status = "Enabled"
    filter { prefix = var.lifecycle_prefix }
    transition {
      days          = var.deep_archive_days
      storage_class = "DEEP_ARCHIVE"
    }
  }
}
