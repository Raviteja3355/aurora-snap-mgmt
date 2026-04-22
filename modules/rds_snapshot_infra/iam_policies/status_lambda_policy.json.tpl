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
      "Sid": "DescribeExportTasks",
      "Effect": "Allow",
      "Action": "rds:DescribeExportTasks",
      "Resource": "*"
    },
    {
      "Sid": "DeleteSnapshots",
      "Effect": "Allow",
      "Action": [
        "rds:DeleteDBSnapshot",
        "rds:DeleteDBClusterSnapshot"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DeleteBackupRecoveryPoints",
      "Effect": "Allow",
      "Action": "backup:DeleteRecoveryPoint",
      "Resource": "*"
    },
    {
      "Sid": "S3ReadAccess",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "${s3_bucket_arn}"
    },
    {
      "Sid": "S3GetObjects",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "${s3_bucket_arn}/*"
    },
    {
      "Sid": "KMSAccess",
      "Effect": "Allow",
      "Action": [
        "kms:GenerateDataKey*",
        "kms:DescribeKey",
        "kms:Decrypt"
      ],
      "Resource": "${kms_key_arn}"
    },
    {
      "Sid": "DynamoDBProcessedTasks",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem",
        "dynamodb:Scan"
      ],
      "Resource": "${dynamodb_table_arn}"
    },
    {
      "Sid": "InvokeCleanupLambda",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "${cleanup_lambda_arn}"
    }
  ]
}
