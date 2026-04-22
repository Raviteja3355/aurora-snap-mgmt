import os
import re
import json
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timezone

rds = boto3.client("rds")

ARCHIVE_BUCKET  = os.environ["ARCHIVE_BUCKET"]
EXPORT_ROLE_ARN = os.environ["EXPORT_ROLE_ARN"]
KMS_KEY_ARN     = os.environ["KMS_KEY_ARN"]
DRY_RUN_MODE    = os.environ.get("DRY_RUN_MODE", "false").lower() == "true"

_SKIP_STATUSES = {"STARTING", "IN_PROGRESS", "COMPLETE"}


def _make_export_task_id(snapshot_id):
    """
    Build a valid RDS export task identifier unique per invocation.
    Rules: starts with a letter, only ASCII letters/digits/hyphens,
    no consecutive hyphens, max 60 chars.
    """
    clean = re.sub(r"[^A-Za-z0-9-]", "-", snapshot_id)
    clean = re.sub(r"-{2,}", "-", clean).strip("-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    raw = f"exp-{clean}-{timestamp}"
    return raw[:60].rstrip("-")


def _find_active_export(snapshot_arn):
    """
    Return the task identifier of any active or completed export for this snapshot,
    or None if no such task exists.
    Tasks in FAILED or CANCELED state are not returned — they are eligible for retry.
    Returns the task ID so callers (including the SFN pipeline) can continue monitoring it.
    """
    marker = None
    while True:
        kwargs = {"SourceArn": snapshot_arn}
        if marker:
            kwargs["Marker"] = marker
        resp = rds.describe_export_tasks(**kwargs)
        for task in resp.get("ExportTasks", []):
            if task["Status"] in _SKIP_STATUSES:
                print(
                    f"Found existing export task {task['ExportTaskIdentifier']} "
                    f"with status {task['Status']} for {snapshot_arn}"
                )
                return task["ExportTaskIdentifier"]
        marker = resp.get("Marker")
        if not marker:
            break
    return None


def handler(event, context):
    if isinstance(event, str):
        event = json.loads(event)

    snapshot_id  = event["snapshot_identifier"]
    snapshot_arn = event["snapshot_arn"]

    existing_task_id = _find_active_export(snapshot_arn)
    if existing_task_id:
        print(f"Skipping {snapshot_id}: export {existing_task_id} is already active or complete")
        return {"skipped": True, "snapshot_identifier": snapshot_id, "export_task_identifier": existing_task_id}

    export_id = _make_export_task_id(snapshot_id)
    s3_prefix = f"snapshots/{snapshot_id}"

    if DRY_RUN_MODE:
        print(f"[DRY RUN] Would start export task '{export_id}' for {snapshot_id}")
        return {
            "dry_run": True,
            "export_task_identifier": export_id,
            "snapshot_identifier": snapshot_id,
            "s3_prefix": s3_prefix
        }

    try:
        resp = rds.start_export_task(
            ExportTaskIdentifier=export_id,
            SourceArn=snapshot_arn,
            S3BucketName=ARCHIVE_BUCKET,
            S3Prefix=s3_prefix,
            IamRoleArn=EXPORT_ROLE_ARN,
            KmsKeyId=KMS_KEY_ARN
        )
    except ClientError as e:
        # Race condition: two concurrent invocations both passed the existence check
        if e.response["Error"]["Code"] == "ExportTaskAlreadyExistsFault":
            print(f"Export task already exists for {snapshot_id} (race condition caught)")
            return {"skipped": True, "snapshot_identifier": snapshot_id, "reason": "race_condition"}
        raise

    return {
        "export_task_identifier": resp["ExportTaskIdentifier"],
        "snapshot_identifier": snapshot_id,
        "s3_prefix": s3_prefix
    }
