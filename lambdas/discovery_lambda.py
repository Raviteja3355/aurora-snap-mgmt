import os
import re
import json
import random
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timezone, timedelta

rds           = boto3.client("rds")
lambda_client = boto3.client("lambda")

RETENTION_DAYS         = int(os.environ.get("RETENTION_DAYS", "730"))
EXPORT_LAMBDA_ARN      = os.environ.get("EXPORT_LAMBDA_ARN", "")
ARCHIVE_BUCKET         = os.environ["ARCHIVE_BUCKET"]
DRY_RUN_MODE           = os.environ.get("DRY_RUN_MODE", "false").lower() == "true"
MAX_EXPORT_CONCURRENCY = int(os.environ.get("MAX_EXPORT_CONCURRENCY", "5"))

# When true, only Aurora cluster snapshots are eligible — RDS instance snapshots are skipped.
AURORA_ONLY = os.environ.get("AURORA_ONLY", "false").lower() == "true"

# When running inside a Step Functions state machine, skip Lambda invocations —
# the state machine Map state drives per-snapshot concurrency instead.
SFN_MODE = os.environ.get("SFN_MODE", "false").lower() == "true"

TARGET_CLUSTER_IDENTIFIERS = [
    c.strip()
    for c in os.environ.get("TARGET_CLUSTER_IDENTIFIERS", "").split(",")
    if c.strip()
]
SNAPSHOT_NAME_PATTERN = os.environ.get("SNAPSHOT_NAME_PATTERN", "")


def _get_export_task_state():
    """
    Single scan of all export tasks for this bucket. Returns:
      - in_progress_count : tasks currently STARTING or IN_PROGRESS
      - skip_arns         : snapshot ARNs to exclude from triggering —
                            includes both in-progress AND already-COMPLETE
                            exports so we never re-trigger a running or
                            already-exported snapshot.
    """
    in_progress_count = 0
    skip_arns         = set()
    paginator         = rds.get_paginator("describe_export_tasks")
    for page in paginator.paginate():
        for task in page["ExportTasks"]:
            if task.get("S3Bucket") != ARCHIVE_BUCKET:
                continue
            status = task["Status"]
            if status in ("STARTING", "IN_PROGRESS"):
                in_progress_count += 1
                skip_arns.add(task["SourceArn"])
            elif status == "COMPLETE":
                skip_arns.add(task["SourceArn"])
    return in_progress_count, skip_arns


def _list_manual_snapshots(cutoff):
    """
    List eligible manual snapshots that have aged past the retention threshold.
    When AURORA_ONLY=true, only Aurora cluster snapshots are returned.
    Otherwise both RDS instance and Aurora cluster snapshots are returned.
    """
    eligible = []

    # --- RDS instance manual snapshots (skipped when AURORA_ONLY=true) ---
    if not AURORA_ONLY:
        paginator = rds.get_paginator("describe_db_snapshots")
        for page in paginator.paginate(SnapshotType="manual"):
            for snap in page["DBSnapshots"]:
                if snap.get("Status") != "available":
                    continue

                creation_time = snap["SnapshotCreateTime"]
                if creation_time.tzinfo is None:
                    creation_time = creation_time.replace(tzinfo=timezone.utc)
                if creation_time > cutoff:
                    continue

                snapshot_id  = snap["DBSnapshotIdentifier"]
                snapshot_arn = snap["DBSnapshotArn"]

                if TARGET_CLUSTER_IDENTIFIERS:
                    if snap["DBInstanceIdentifier"] not in TARGET_CLUSTER_IDENTIFIERS:
                        continue

                if SNAPSHOT_NAME_PATTERN:
                    if not re.search(SNAPSHOT_NAME_PATTERN, snapshot_id):
                        continue

                eligible.append({
                    "DBSnapshotIdentifier": snapshot_id,
                    "DBSnapshotArn":        snapshot_arn,
                })

    # --- Aurora cluster manual snapshots ---
    paginator = rds.get_paginator("describe_db_cluster_snapshots")
    for page in paginator.paginate(SnapshotType="manual"):
        for snap in page["DBClusterSnapshots"]:
            if snap.get("Status") != "available":
                continue

            creation_time = snap["SnapshotCreateTime"]
            if creation_time.tzinfo is None:
                creation_time = creation_time.replace(tzinfo=timezone.utc)
            if creation_time > cutoff:
                continue

            snapshot_id  = snap["DBClusterSnapshotIdentifier"]
            snapshot_arn = snap["DBClusterSnapshotArn"]

            if TARGET_CLUSTER_IDENTIFIERS:
                if snap["DBClusterIdentifier"] not in TARGET_CLUSTER_IDENTIFIERS:
                    continue

            if SNAPSHOT_NAME_PATTERN:
                if not re.search(SNAPSHOT_NAME_PATTERN, snapshot_id):
                    continue

            eligible.append({
                "DBSnapshotIdentifier": snapshot_id,
                "DBSnapshotArn":        snapshot_arn,
            })

    return eligible


def handler(event, context):
    cutoff   = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    eligible = _list_manual_snapshots(cutoff)

    # Shuffle so the same snapshots do not always consume the concurrency budget
    random.shuffle(eligible)

    # SFN_MODE: return the snapshot list only — the state machine Map state
    # handles per-snapshot invocations and concurrency capping.
    mode_label = "AURORA_ONLY" if AURORA_ONLY else "ALL"
    if SFN_MODE:
        snapshots = [
            {"snapshot_identifier": s["DBSnapshotIdentifier"], "snapshot_arn": s["DBSnapshotArn"], "retry_count": 0}
            for s in eligible
        ]
        print(f"SFN_MODE [{mode_label}]: returning {len(snapshots)} eligible snapshot(s) for state machine processing")
        return {"snapshots": snapshots}

    in_progress, skip_arns = _get_export_task_state()

    # Exclude snapshots already running or already exported — only untriggered ones
    eligible = [s for s in eligible if s["DBSnapshotArn"] not in skip_arns]

    if DRY_RUN_MODE:
        print(f"[DRY RUN] [{mode_label}] Would invoke export for {len(eligible)} untriggered snapshot(s) "
              f"({in_progress} already in-progress)")
        return {
            "dry_run": True,
            "eligible_snapshots": [s["DBSnapshotIdentifier"] for s in eligible]
        }

    available_slots = max(0, MAX_EXPORT_CONCURRENCY - in_progress)
    batch           = eligible[:available_slots]

    invoked = []
    errors  = []
    for snap in batch:
        payload = {
            "snapshot_identifier": snap["DBSnapshotIdentifier"],
            "snapshot_arn":        snap["DBSnapshotArn"],
        }
        try:
            lambda_client.invoke(
                FunctionName=EXPORT_LAMBDA_ARN,
                InvocationType="Event",
                Payload=json.dumps(payload)
            )
            invoked.append(snap["DBSnapshotIdentifier"])
        except ClientError as e:
            print(f"Failed to invoke export for {snap['DBSnapshotIdentifier']}: {e}")
            errors.append({"snapshot": snap["DBSnapshotIdentifier"], "error": str(e)})

    return {
        "eligible_count":    len(eligible),
        "in_progress_count": in_progress,
        "skipped_count":     len(skip_arns),
        "available_slots":   available_slots,
        "invoked_count":     len(invoked),
        "invoked_snapshots": invoked,
        "errors":            errors
    }
