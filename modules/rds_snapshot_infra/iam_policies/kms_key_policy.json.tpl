{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EnableRootPermissions",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::${account_id}:root"
      },
      "Action": "kms:*",
      "Resource": "*"
    },
    {
      "Sid": "AllowRDSExportRoleToUseKey",
      "Effect": "Allow",
      "Principal": {
        "AWS": "${rds_export_role_arn}"
      },
      "Action": [
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:ReEncrypt*",
        "kms:GenerateDataKey*",
        "kms:DescribeKey",
        "kms:CreateGrant",
        "kms:RetireGrant"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AllowExportLambdaRoleToUseKey",
      "Effect": "Allow",
      "Principal": {
        "AWS": "${export_lambda_role_arn}"
      },
      "Action": [
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:ReEncrypt*",
        "kms:GenerateDataKey*",
        "kms:DescribeKey",
        "kms:CreateGrant",
        "kms:RetireGrant"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AllowStatusLambdaRoleToUseKey",
      "Effect": "Allow",
      "Principal": {
        "AWS": "${status_lambda_role_arn}"
      },
      "Action": [
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:GenerateDataKey*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AllowRDSServiceToUseKey",
      "Effect": "Allow",
      "Principal": {
        "Service": "rds.amazonaws.com"
      },
      "Action": [
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:ReEncrypt*",
        "kms:GenerateDataKey*",
        "kms:DescribeKey",
        "kms:CreateGrant",
        "kms:RetireGrant"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "rds.${region}.amazonaws.com"
        }
      }
    },
    {
      "Sid": "AllowRDSExportServiceToUseKey",
      "Effect": "Allow",
      "Principal": {
        "Service": "export.rds.amazonaws.com"
      },
      "Action": [
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:ReEncrypt*",
        "kms:GenerateDataKey*",
        "kms:DescribeKey",
        "kms:CreateGrant",
        "kms:RetireGrant"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "rds.${region}.amazonaws.com"
        }
      }
    }
  ]
}
