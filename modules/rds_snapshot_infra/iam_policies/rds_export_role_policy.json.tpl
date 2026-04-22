{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3AccessForRDSExport",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:ListBucket",
        "s3:GetObject",
        "s3:GetBucketLocation",
        "s3:DeleteObject"
      ],
      "Resource": [
        "${s3_bucket_arn}",
        "${s3_bucket_arn}/*"
      ]
    },
    {
      "Sid": "KMSAccessForRDSExport",
      "Effect": "Allow",
      "Action": [
        "kms:GenerateDataKey*",
        "kms:Encrypt",
        "kms:DescribeKey",
        "kms:Decrypt",
        "kms:CreateGrant"
      ],
      "Resource": "${kms_key_arn}"
    }
  ]
}
