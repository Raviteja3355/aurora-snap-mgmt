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
      "Sid": "S3ListBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "${s3_bucket_arn}"
    },
    {
      "Sid": "S3DeleteObjects",
      "Effect": "Allow",
      "Action": "s3:DeleteObject",
      "Resource": "${s3_bucket_arn}/*"
    }
  ]
}
