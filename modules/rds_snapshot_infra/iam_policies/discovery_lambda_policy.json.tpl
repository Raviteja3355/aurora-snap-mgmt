{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:PutLogEvents",
        "logs:CreateLogStream",
        "logs:CreateLogGroup"
      ],
      "Resource": "*"
    },
    {
      "Sid": "RDSReadOnly",
      "Effect": "Allow",
      "Action": [
        "rds:DescribeDBSnapshots",
        "rds:DescribeDBClusterSnapshots",
        "rds:DescribeExportTasks"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BackupReadOnly",
      "Effect": "Allow",
      "Action": [
        "backup:ListRecoveryPointsByBackupVault",
        "backup:DescribeRecoveryPoint"
      ],
      "Resource": "*"
    },
    {
      "Sid": "InvokeOtherLambdas",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "*"
    },
    {
      "Sid": "S3AccessForWorkflow",
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
      "Sid": "KMSAccessForWorkflow",
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
