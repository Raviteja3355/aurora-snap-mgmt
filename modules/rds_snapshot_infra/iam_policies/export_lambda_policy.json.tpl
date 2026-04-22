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
      "Sid": "RDSExportPermissions",
      "Effect": "Allow",
      "Action": [
        "rds:StartExportTask",
        "rds:DescribeExportTasks"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PassRDSExportRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::${account_id}:role/${rds_export_role_name}"
    },
    {
      "Sid": "KMSAccessForExport",
      "Effect": "Allow",
      "Action": [
        "kms:GenerateDataKey*",
        "kms:DescribeKey",
        "kms:Decrypt"
      ],
      "Resource": "${kms_key_arn}"
    },
    {
      "Sid": "SQSDLQAccess",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${dlq_arn}"
    }
  ]
}
