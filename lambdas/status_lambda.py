import os
import json
import urllib.request
import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from datetime import datetime, timezone, timedelta

rds           = boto3.client("rds")
backup_client = boto3.client("backup")
s3            = boto3.client("s3")
dynamodb      = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")
sfn_client    = boto3.client("stepfunctions")

BUCKET_NAME       = os.environ["BUCKET_NAME"]
BACKUP_VAULT_NAME = os.environ["BACKUP_VAULT_NAME"]
DRY_RUN_MODE      = os.environ.get("DRY_RUN_MODE", "false").lower() == "true"

DELETE_SOURCE_AFTER_EXPORT = os.environ.get("DELETE_SOURCE_AFTER_EXPORT", "false").lower() == "true"
DELETE_DELAY_DAYS          = int(os.environ.get("DELETE_DELAY_DAYS", "7"))

EXPORT_TASK_LOOKBACK_DAYS = int(os.environ.get("EXPORT_TASK_LOOKBACK_DAYS", "90"))

PROCESSED_TASKS_TABLE = os.environ.get("PROCESSED_TASKS_TABLE", "")

# Retry configuration
EXPORT_LAMBDA_ARN   = os.environ.get("EXPORT_LAMBDA_ARN", "")
CLEANUP_LAMBDA_ARN  = os.environ.get("CLEANUP_LAMBDA_ARN", "")
CLEANUP_DELAY_HOURS = int(os.environ.get("CLEANUP_DELAY_HOURS", "1"))
MAX_RETRIES         = int(os.environ.get("MAX_RETRIES", "5"))

# SFN mode: export SFN name used by maintenance pipeline to start retry executions.
# Passed as a name (not ARN) to avoid circular Terraform dependency.
# The ARN is derived at runtime from the Lambda execution context.
EXPORT_SFN_NAME = os.environ.get("EXPORT_SFN_NAME", "")

# When running inside a Step Functions state machine, the state machine drives
# per-snapshot invocations — Lambda returns an outcome key instead of looping.
SFN_MODE = os.environ.get("SFN_MODE", "false").lower() == "true"

# Microsoft Teams incoming webhook URLs.
# In Teams: channel → Connectors → Incoming Webhook → copy the URL.
# Leave any URL empty to disable that notification channel.
TEAMS_SUCCESS_WEBHOOK_URL          = os.environ.get("TEAMS_SUCCESS_WEBHOOK_URL", "")
TEAMS_FAILURE_WEBHOOK_URL          = os.environ.get("TEAMS_FAILURE_WEBHOOK_URL", "")
TEAMS_PENDING_DELETION_WEBHOOK_URL = os.environ.get("TEAMS_PENDING_DELETION_WEBHOOK_URL", "")
TEAMS_DELETED_WEBHOOK_URL          = os.environ.get("TEAMS_DELETED_WEBHOOK_URL", "")


# ---------------------------------------------------------------------------
# State tracking
# DynamoDB keys:
#   export:{export_id}   — task fully resolved (no further processing)
#   notif:{export_id}    — success / integrity-failure notification already sent
#   pending:{export_id}  — pending-deletion notification already sent
# ---------------------------------------------------------------------------

def _is_task_processed(key):
    if not PROCESSED_TASKS_TABLE:
        return False
    table = dynamodb.Table(PROCESSED_TASKS_TABLE)
    return "Item" in table.get_item(Key={"task_id": key})


def _mark_task_processed(key):
    if not PROCESSED_TASKS_TABLE or DRY_RUN_MODE:
        return
    table = dynamodb.Table(PROCESSED_TASKS_TABLE)
    ttl   = int((datetime.now(timezone.utc) + timedelta(days=90)).timestamp())
    table.put_item(Item={
        "task_id":      key,
        "ttl":          ttl,
        "processed_at": datetime.now(timezone.utc).isoformat()
    })


def _get_retry_count(snapshot_arn):
    """Return how many retries have been attempted for this snapshot."""
    if not PROCESSED_TASKS_TABLE:
        return 0
    table = dynamodb.Table(PROCESSED_TASKS_TABLE)
    key   = f"retry:{snapshot_arn}"
    resp  = table.get_item(Key={"task_id": key})
    return int(resp["Item"].get("count", 0)) if "Item" in resp else 0


def _increment_retry_count(snapshot_arn):
    """Increment retry counter for this snapshot and return the new count."""
    if not PROCESSED_TASKS_TABLE or DRY_RUN_MODE:
        return 0
    table = dynamodb.Table(PROCESSED_TASKS_TABLE)
    key   = f"retry:{snapshot_arn}"
    ttl   = int((datetime.now(timezone.utc) + timedelta(days=90)).timestamp())
    resp  = table.update_item(
        Key={"task_id": key},
        UpdateExpression="SET #c = if_not_exists(#c, :zero) + :one, #t = :ttl",
        ExpressionAttributeNames={"#c": "count", "#t": "ttl"},
        ExpressionAttributeValues={":zero": 0, ":one": 1, ":ttl": ttl},
        ReturnValues="UPDATED_NEW"
    )
    return int(resp["Attributes"]["count"])


def _trigger_retry(snapshot_arn, snapshot_id, attempt):
    """Invoke the export lambda asynchronously to retry the export."""
    if not EXPORT_LAMBDA_ARN or DRY_RUN_MODE:
        print(f"[DRY RUN] Would retry export for {snapshot_id} (attempt {attempt})")
        return
    payload = json.dumps({
        "snapshot_identifier": snapshot_id,
        "snapshot_arn":        snapshot_arn,
    }).encode("utf-8")
    lambda_client.invoke(
        FunctionName=EXPORT_LAMBDA_ARN,
        InvocationType="Event",
        Payload=payload
    )
    print(f"Retry attempt {attempt} triggered for {snapshot_id}")


def _invoke_cleanup_lambda(export_task_id, s3_prefix):
    """Invoke the cleanup lambda asynchronously to delete partial S3 objects."""
    if not CLEANUP_LAMBDA_ARN:
        print(f"CLEANUP_LAMBDA_ARN not set — skipping S3 cleanup for {export_task_id}")
        return
    if DRY_RUN_MODE:
        print(f"[DRY RUN] Would invoke cleanup lambda for {export_task_id}")
        return
    payload = json.dumps({
        "task": {
            "ExportTaskIdentifier": export_task_id,
            "S3Prefix":             s3_prefix,
        }
    }).encode("utf-8")
    lambda_client.invoke(
        FunctionName=CLEANUP_LAMBDA_ARN,
        InvocationType="Event",
        Payload=payload
    )
    print(f"Cleanup lambda invoked for {export_task_id}")


def _schedule_deletion(snapshot_arn, export_task_id, task_end_time):
    """
    Write a deletion_pending DynamoDB entry for a successfully exported snapshot.
    The maintenance pipeline picks this up after DELETE_DELAY_DAYS and deletes
    the source snapshot, then sends the deleted notification.
    No-op when DELETE_SOURCE_AFTER_EXPORT is disabled or DynamoDB is not configured.
    """
    if not DELETE_SOURCE_AFTER_EXPORT or not PROCESSED_TASKS_TABLE or DRY_RUN_MODE:
        return
    if task_end_time is None:
        return

    if task_end_time.tzinfo is None:
        task_end_time = task_end_time.replace(tzinfo=timezone.utc)

    delete_after = int((task_end_time + timedelta(days=DELETE_DELAY_DAYS)).timestamp())
    ttl          = int((datetime.now(timezone.utc) + timedelta(days=DELETE_DELAY_DAYS + 30)).timestamp())
    table        = dynamodb.Table(PROCESSED_TASKS_TABLE)
    key          = f"deletion_pending:{snapshot_arn}"

    if "Item" in table.get_item(Key={"task_id": key}):
        print(f"Deletion already scheduled for {snapshot_arn} — skipping")
        return

    table.put_item(Item={
        "task_id":        key,
        "snapshot_arn":   snapshot_arn,
        "export_task_id": export_task_id,
        "delete_after":   delete_after,
        "ttl":            ttl,
        "scheduled_at":   datetime.now(timezone.utc).isoformat(),
    })
    print(f"Deletion scheduled for {snapshot_arn} — will run after {DELETE_DELAY_DAYS}d delay")


def _schedule_retry(snapshot_arn, snapshot_identifier, current_retry_count):
    """
    Write a retry_pending DynamoDB entry for a failed export.
    The maintenance pipeline picks this up and starts a new targeted Export SFN
    execution for just this snapshot, avoiding long retry loops inside the Map state.
    """
    if not PROCESSED_TASKS_TABLE or DRY_RUN_MODE:
        return
    next_retry_count = current_retry_count + 1
    # 30-minute delay before retry — lets AWS settle after a failed export
    retry_after = int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp())
    ttl         = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    table       = dynamodb.Table(PROCESSED_TASKS_TABLE)
    table.put_item(Item={
        "task_id":             f"retry_pending:{snapshot_arn}",
        "snapshot_arn":        snapshot_arn,
        "snapshot_identifier": snapshot_identifier,
        "retry_count":         next_retry_count,
        "retry_after":         retry_after,
        "ttl":                 ttl,
        "scheduled_at":        datetime.now(timezone.utc).isoformat(),
    })
    print(f"Retry {next_retry_count} scheduled for {snapshot_identifier} in 30 minutes")


def _get_export_sfn_arn(context):
    """
    Derive the Export SFN ARN from the Lambda execution context and SFN name.
    Uses context.invoked_function_arn to extract region and account ID without
    needing an extra API call or hardcoded values.
    """
    if not EXPORT_SFN_NAME or not context:
        return ""
    parts      = context.invoked_function_arn.split(":")
    region     = parts[3]
    account_id = parts[4]
    return f"arn:aws:states:{region}:{account_id}:stateMachine:{EXPORT_SFN_NAME}"


def _process_pending_retries(context):
    """
    Find retry_pending DynamoDB entries whose delay has elapsed and start a new
    targeted Export SFN execution containing just those snapshots. This keeps
    retries out of the Map state so the export pipeline finishes quickly.
    """
    if not PROCESSED_TASKS_TABLE or not EXPORT_SFN_NAME:
        return

    export_sfn_arn = _get_export_sfn_arn(context)
    if not export_sfn_arn:
        return

    now   = int(datetime.now(timezone.utc).timestamp())
    table = dynamodb.Table(PROCESSED_TASKS_TABLE)
    resp  = table.scan(
        FilterExpression=Attr("task_id").begins_with("retry_pending:") & Attr("retry_after").lte(now)
    )

    items = resp.get("Items", [])
    if not items:
        return

    snapshots = []
    for item in items:
        snapshots.append({
            "snapshot_identifier": item["snapshot_identifier"],
            "snapshot_arn":        item["snapshot_arn"],
            "retry_count":         int(item.get("retry_count", 1)),
        })

    if DRY_RUN_MODE:
        print(f"[DRY RUN] Would start retry SFN execution for {len(snapshots)} snapshot(s)")
        return

    execution_name = f"retry-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    sfn_client.start_execution(
        stateMachineArn=export_sfn_arn,
        name=execution_name,
        input=json.dumps({"snapshots": snapshots})
    )
    print(f"Started retry execution '{execution_name}' for {len(snapshots)} snapshot(s)")

    for item in items:
        table.delete_item(Key={"task_id": item["task_id"]})


def _delete_snapshot_directly(snapshot_arn):
    """
    Delete a snapshot without a delay check.
    Used by the maintenance handler when the delay has already been confirmed elapsed.
    """
    if DRY_RUN_MODE:
        print(f"[DRY RUN] Would delete {snapshot_arn}")
        return {"outcome": "skipped", "reason": "dry_run"}

    if _is_backup_recovery_point(snapshot_arn):
        backup_client.delete_recovery_point(
            BackupVaultName=BACKUP_VAULT_NAME,
            RecoveryPointArn=snapshot_arn
        )
    elif _is_cluster_snapshot(snapshot_arn):
        snapshot_id = _extract_snapshot_id(snapshot_arn)
        rds.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapshot_id)
    else:
        snapshot_id = _extract_snapshot_id(snapshot_arn)
        rds.delete_db_snapshot(DBSnapshotIdentifier=snapshot_id)

    return {
        "outcome":     "deleted",
        "deleted_at":  datetime.now(timezone.utc).isoformat(),
        "source_type": _source_type_label(snapshot_arn),
    }


def _process_pending_deletions():
    """
    Find deletion_pending DynamoDB entries whose delay has elapsed, delete the
    source snapshot, send the deleted notification, and remove the entry.
    Called by the maintenance handler.
    """
    if not PROCESSED_TASKS_TABLE or not DELETE_SOURCE_AFTER_EXPORT:
        return

    now   = int(datetime.now(timezone.utc).timestamp())
    table = dynamodb.Table(PROCESSED_TASKS_TABLE)
    resp  = table.scan(
        FilterExpression=Attr("task_id").begins_with("deletion_pending:") & Attr("delete_after").lte(now)
    )

    for item in resp.get("Items", []):
        snapshot_arn   = item.get("snapshot_arn", "")
        export_task_id = item.get("export_task_id", "")
        if not snapshot_arn:
            continue
        print(f"Deletion delay elapsed — deleting {snapshot_arn}")
        try:
            deletion_result = _delete_snapshot_directly(snapshot_arn)
            notify_deleted(export_task_id, snapshot_arn, deletion_result)
            table.delete_item(Key={"task_id": f"deletion_pending:{snapshot_arn}"})
        except Exception as e:
            print(f"Failed to process deletion for {snapshot_arn}: {e}")


def _schedule_cleanup(task):
    """
    Schedule cleanup of partial S3 objects after CLEANUP_DELAY_HOURS.
    Writes a cleanup_pending record to DynamoDB. The maintenance pipeline picks it
    up after the delay has elapsed, then invokes the cleanup lambda. This ensures
    AWS has fully finalized the failed export before we delete anything.
    """
    export_task_id = task["ExportTaskIdentifier"]
    s3_prefix      = task.get("S3Prefix", "")

    if not CLEANUP_LAMBDA_ARN:
        print(f"CLEANUP_LAMBDA_ARN not set — skipping cleanup scheduling for {export_task_id}")
        return
    if DRY_RUN_MODE:
        print(f"[DRY RUN] Would schedule cleanup for {export_task_id} in {CLEANUP_DELAY_HOURS}h")
        return
    if not PROCESSED_TASKS_TABLE:
        # No DynamoDB — fall back to immediate invocation
        _invoke_cleanup_lambda(export_task_id, s3_prefix)
        return

    cleanup_after = int((datetime.now(timezone.utc) + timedelta(hours=CLEANUP_DELAY_HOURS)).timestamp())
    ttl           = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    table         = dynamodb.Table(PROCESSED_TASKS_TABLE)
    table.put_item(Item={
        "task_id":        f"cleanup_pending:{export_task_id}",
        "export_task_id": export_task_id,
        "s3_prefix":      s3_prefix,
        "cleanup_after":  cleanup_after,
        "ttl":            ttl,
        "scheduled_at":   datetime.now(timezone.utc).isoformat(),
    })
    print(f"Cleanup scheduled for {export_task_id} — will run after {CLEANUP_DELAY_HOURS}h delay")


def _process_pending_cleanups():
    """
    Find cleanup_pending DynamoDB entries whose delay has elapsed and invoke
    the cleanup lambda for each. Called at the start of every status lambda run.
    """
    if not PROCESSED_TASKS_TABLE or not CLEANUP_LAMBDA_ARN:
        return

    now   = int(datetime.now(timezone.utc).timestamp())
    table = dynamodb.Table(PROCESSED_TASKS_TABLE)
    resp  = table.scan(
        FilterExpression=Attr("task_id").begins_with("cleanup_pending:") & Attr("cleanup_after").lte(now)
    )

    for item in resp.get("Items", []):
        export_task_id = item.get("export_task_id", "")
        s3_prefix      = item.get("s3_prefix", "")
        print(f"Delay elapsed — invoking cleanup for {export_task_id}")
        try:
            _invoke_cleanup_lambda(export_task_id, s3_prefix)
            table.delete_item(Key={"task_id": f"cleanup_pending:{export_task_id}"})
        except Exception as e:
            print(f"Failed to invoke cleanup for {export_task_id}: {e}")


# ---------------------------------------------------------------------------
# ARN helpers
# ---------------------------------------------------------------------------

def _is_cluster_snapshot(snapshot_arn):
    return ":cluster-snapshot:" in snapshot_arn


def _is_backup_recovery_point(snapshot_arn):
    """
    Return True if this snapshot was created by AWS Backup.
    Backup recovery point ARNs contain 'awsbackup' in the last segment:
    e.g. arn:aws:rds:...:snapshot:awsbackup-job-20240101t000000-abc123
    """
    return "awsbackup" in snapshot_arn.split(":")[-1].lower()


def _extract_snapshot_id(snapshot_arn):
    if _is_cluster_snapshot(snapshot_arn):
        return snapshot_arn.split(":cluster-snapshot:")[-1]
    return snapshot_arn.split(":snapshot:")[-1]


def _source_type_label(snapshot_arn):
    if _is_backup_recovery_point(snapshot_arn):
        return "backup_recovery_point"
    if _is_cluster_snapshot(snapshot_arn):
        return "rds_cluster_snapshot"
    return "rds_instance_snapshot"


def _snapshot_type_label(snapshot_arn):
    """
    Human-readable label for notification titles and headers.
    Distinguishes Aurora cluster snapshots from RDS instance snapshots.
    """
    if _is_backup_recovery_point(snapshot_arn):
        return "AWS BACKUP"
    if _is_cluster_snapshot(snapshot_arn):
        return "AURORA CLUSTER"
    return "RDS INSTANCE"


# ---------------------------------------------------------------------------
# Export task listing — scoped to this pipeline's bucket and time window
# ---------------------------------------------------------------------------

def list_export_tasks():
    tasks           = []
    lookback_cutoff = datetime.now(timezone.utc) - timedelta(days=EXPORT_TASK_LOOKBACK_DAYS)
    paginator       = rds.get_paginator("describe_export_tasks")

    for page in paginator.paginate():
        for task in page["ExportTasks"]:
            if task.get("S3Bucket") != BUCKET_NAME:
                continue
            task_start_time = task.get("TaskStartTime")
            if task_start_time:
                if task_start_time.tzinfo is None:
                    task_start_time = task_start_time.replace(tzinfo=timezone.utc)
                if task_start_time < lookback_cutoff:
                    continue
            tasks.append(task)

    return tasks


# ---------------------------------------------------------------------------
# S3 integrity helpers
# ---------------------------------------------------------------------------

def get_s3_objects(prefix):
    objs      = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []):
            objs.append(obj)
    return objs


def load_json_object(key):
    resp = s3.get_object(Bucket=BUCKET_NAME, Key=key)
    body = resp["Body"].read()
    if len(body) == 0:
        raise ValueError(f"Empty JSON file: {key}")
    return json.loads(body)


def check_integrity_for_export(task):
    snapshot_arn = task["SourceArn"]
    snapshot_id  = _extract_snapshot_id(snapshot_arn)
    prefix       = f"snapshots/{snapshot_id}/"
    objs         = get_s3_objects(prefix)

    if not objs:
        raise ValueError(f"No objects found under prefix {prefix}")

    keys       = [o["Key"] for o in objs]
    info_key   = next((k for k in keys if "export_info_" in k and k.endswith(".json")), None)
    tables_key = next((k for k in keys if "export_tables_info_" in k and k.endswith(".json")), None)

    if not info_key:
        raise ValueError(f"export_info json not found under {prefix}")
    if not tables_key:
        raise ValueError(f"export_tables_info json not found under {prefix}")

    info_json   = load_json_object(info_key)
    tables_json = load_json_object(tables_key)

    if "SourceArn" not in info_json and "sourceArn" not in info_json:
        raise ValueError("export_info json missing SourceArn/sourceArn")
    if not isinstance(tables_json, (dict, list)):
        raise ValueError("export_tables_info json has unexpected structure")

    # Count exported tables from tables_info JSON
    table_count = 0
    try:
        entries = tables_json if isinstance(tables_json, list) else tables_json.get("tableStatistics", [])
        table_count = len(entries)
    except Exception:
        pass

    # S3 object count and total size
    parquet_objs = [o for o in objs if o["Key"].endswith(".parquet")]
    object_count = len(parquet_objs)
    total_bytes  = sum(o.get("Size", 0) for o in parquet_objs)
    if total_bytes >= 1_073_741_824:
        size_str = f"{total_bytes / 1_073_741_824:.2f} GB"
    elif total_bytes >= 1_048_576:
        size_str = f"{total_bytes / 1_048_576:.2f} MB"
    else:
        size_str = f"{total_bytes / 1024:.1f} KB"

    return {
        "info_key":     info_key,
        "tables_key":   tables_key,
        "table_count":  table_count,
        "object_count": object_count,
        "size_str":     size_str,
        "s3_prefix":    prefix,
    }


# ---------------------------------------------------------------------------
# Deletion — routes to correct API based on snapshot origin
# Returns dict: { outcome: "deleted" | "pending" | "skipped", ...extra }
# ---------------------------------------------------------------------------

def maybe_delete_snapshot(snapshot_arn, task_end_time):
    if not DELETE_SOURCE_AFTER_EXPORT:
        return {"outcome": "skipped", "reason": "flag_disabled"}
    if task_end_time is None:
        return {"outcome": "skipped", "reason": "no_end_time"}

    if task_end_time.tzinfo is None:
        task_end_time = task_end_time.replace(tzinfo=timezone.utc)

    elapsed        = datetime.now(timezone.utc) - task_end_time
    scheduled_date = task_end_time + timedelta(days=DELETE_DELAY_DAYS)

    if elapsed < timedelta(days=DELETE_DELAY_DAYS):
        remaining = DELETE_DELAY_DAYS - elapsed.days
        return {
            "outcome":                 "pending",
            "days_remaining":          remaining,
            "scheduled_deletion_date": scheduled_date.isoformat(),
        }

    if DRY_RUN_MODE:
        print(f"[DRY RUN] Would delete {snapshot_arn}")
        return {"outcome": "skipped", "reason": "dry_run"}

    try:
        if _is_backup_recovery_point(snapshot_arn):
            backup_client.delete_recovery_point(
                BackupVaultName=BACKUP_VAULT_NAME,
                RecoveryPointArn=snapshot_arn
            )
        elif _is_cluster_snapshot(snapshot_arn):
            snapshot_id = _extract_snapshot_id(snapshot_arn)
            rds.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapshot_id)
        else:
            snapshot_id = _extract_snapshot_id(snapshot_arn)
            rds.delete_db_snapshot(DBSnapshotIdentifier=snapshot_id)

        return {
            "outcome":     "deleted",
            "deleted_at":  datetime.now(timezone.utc).isoformat(),
            "source_type": _source_type_label(snapshot_arn),
        }
    except ClientError:
        raise


# ---------------------------------------------------------------------------
# Microsoft Teams notification helpers
# Teams incoming webhook format: POST MessageCard JSON
# Docs: https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/connectors-using
# ---------------------------------------------------------------------------

def _post_to_teams(webhook_url, title, color, facts):
    """
    POST a MessageCard to a Microsoft Teams channel via incoming webhook.
    color: hex string e.g. "00C853" (green), "D50000" (red), "FF6D00" (orange), "9E9E9E" (grey)
    facts: list of {"name": "...", "value": "..."} dicts
    No-op when webhook_url is empty.
    """
    if not webhook_url:
        return
    payload = json.dumps({
        "@type":      "MessageCard",
        "@context":   "http://schema.org/extensions",
        "themeColor": color,
        "summary":    title,
        "sections": [{
            "activityTitle": title,
            "facts":         facts
        }]
    }).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        print(f"Teams notification failed: {e}")


def notify_success(export_id, snapshot_arn, task, integrity):
    """Post to the success channel when an export completes and passes integrity."""
    snapshot_id  = _extract_snapshot_id(snapshot_arn)
    source_type  = _source_type_label(snapshot_arn)
    snap_label   = _snapshot_type_label(snapshot_arn)
    task_start   = task.get("TaskStartTime", "N/A")
    task_end     = task.get("TaskEndTime", "N/A")
    progress     = task.get("PercentProgress", 100)
    data_gb      = task.get("TotalExtractedDataInGB", None)
    warning      = task.get("WarningMessage", "")
    export_only  = task.get("ExportOnly", [])
    kms_key      = task.get("KmsKeyId", "N/A")
    s3_prefix    = task.get("S3Prefix", integrity["s3_prefix"])

    data_str = f"{data_gb:.2f} GB" if data_gb is not None else integrity["size_str"]

    # Calculate duration
    duration_str = "N/A"
    if task.get("TaskStartTime") and task.get("TaskEndTime"):
        start = task["TaskStartTime"]
        end   = task["TaskEndTime"]
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        secs = int((end - start).total_seconds())
        duration_str = f"{secs // 60}m {secs % 60}s"

    tables_scope = ", ".join(export_only) if export_only else "All tables"

    facts = [
        {"name": "Snapshot ID",      "value": snapshot_id},
        {"name": "Source Type",      "value": source_type},
        {"name": "Task ID",          "value": export_id},
        {"name": "Tables Scope",     "value": tables_scope},
        {"name": "Started",          "value": str(task_start)},
        {"name": "Finished",         "value": str(task_end)},
        {"name": "Duration",         "value": duration_str},
        {"name": "Progress",         "value": f"{progress}%"},
        {"name": "Tables Exported",  "value": str(integrity["table_count"])},
        {"name": "Parquet Files",    "value": str(integrity["object_count"])},
        {"name": "Data Size",        "value": data_str},
        {"name": "S3 Bucket",        "value": BUCKET_NAME},
        {"name": "S3 Prefix",        "value": s3_prefix},
        {"name": "Integrity",        "value": "PASSED"},
        {"name": "Deletion In",      "value": f"{DELETE_DELAY_DAYS} day(s)"},
    ]
    if warning:
        facts.append({"name": "Warning", "value": warning})
    _post_to_teams(
        TEAMS_SUCCESS_WEBHOOK_URL,
        title=f"✅  {snap_label.title()} Snapshot Export — SUCCESSFUL",
        color="00C853",
        facts=facts
    )


def notify_retry(export_id, snapshot_arn, status, attempt, max_retries, error=None, task=None):
    """Post to the failure channel each time a retry is triggered."""
    snapshot_id   = _extract_snapshot_id(snapshot_arn)
    source_type   = _source_type_label(snapshot_arn)
    snap_label    = _snapshot_type_label(snapshot_arn)
    task_start    = task.get("TaskStartTime", "N/A") if task else "N/A"
    task_end      = task.get("TaskEndTime",   "N/A") if task else "N/A"
    failure_cause = (task.get("FailureCause") or "") if task else ""

    facts = [
        {"name": "Snapshot ID",    "value": snapshot_id},
        {"name": "Source Type",    "value": source_type},
        {"name": "Task ID",        "value": export_id},
        {"name": "Started",        "value": str(task_start)},
        {"name": "Ended",          "value": str(task_end)},
        {"name": "Status",         "value": status},
    ]
    if failure_cause:
        facts.append({"name": "AWS Cause",    "value": failure_cause})
    if error:
        facts.append({"name": "Error Detail", "value": error})
    facts += [
        {"name": "Attempt",        "value": f"{attempt} of {max_retries}"},
        {"name": "Remaining",      "value": f"{max_retries - attempt} attempt(s) left"},
        {"name": "Total Allowed",  "value": str(max_retries)},
        {"name": "Note",           "value": "New export triggered. Notified on success or exhaustion."},
    ]
    _post_to_teams(
        TEAMS_FAILURE_WEBHOOK_URL,
        title=f"🔄  {snap_label.title()} Snapshot Export — RETRYING",
        color="FF6D00",
        facts=facts
    )


def notify_failure(export_id, snapshot_arn, status, error=None, task=None, retry_count=0, max_retries=0):
    """Post to the failure channel when all retries are exhausted."""
    snapshot_id   = _extract_snapshot_id(snapshot_arn)
    source_type   = _source_type_label(snapshot_arn)
    snap_label    = _snapshot_type_label(snapshot_arn)
    task_start    = task.get("TaskStartTime", "N/A") if task else "N/A"
    task_end      = task.get("TaskEndTime",   "N/A") if task else "N/A"
    failure_cause = (task.get("FailureCause") or "") if task else ""

    facts = [
        {"name": "Snapshot ID",   "value": snapshot_id},
        {"name": "Source Type",   "value": source_type},
        {"name": "Task ID",       "value": export_id},
        {"name": "Started",       "value": str(task_start)},
        {"name": "Ended",         "value": str(task_end)},
        {"name": "Status",        "value": status},
    ]
    if failure_cause:
        facts.append({"name": "AWS Cause",    "value": failure_cause})
    if error:
        facts.append({"name": "Error Detail", "value": error})
    if max_retries:
        facts += [
            {"name": "Attempts Tried",  "value": f"{retry_count} of {max_retries}"},
            {"name": "Total Allowed",   "value": str(max_retries)},
            {"name": "Remaining",       "value": "0 (exhausted)"},
        ]
    facts.append({"name": "Action", "value": "All retries exhausted. Re-trigger manually after resolving."})
    _post_to_teams(
        TEAMS_FAILURE_WEBHOOK_URL,
        title=f"❌  {snap_label.title()} Snapshot Export — FAILED",
        color="D50000",
        facts=facts
    )


def notify_pending_deletion(export_id, snapshot_arn, deletion_info):
    """Post to the pending-deletion channel once per task during the delay window."""
    snapshot_id    = _extract_snapshot_id(snapshot_arn)
    source_type    = _source_type_label(snapshot_arn)
    snap_label     = _snapshot_type_label(snapshot_arn)
    days_remaining = deletion_info["days_remaining"]
    scheduled_date = deletion_info["scheduled_deletion_date"]

    _post_to_teams(
        TEAMS_PENDING_DELETION_WEBHOOK_URL,
        title=f"🗓️  {snap_label.title()} Snapshot — DELETION SCHEDULED",
        color="FF6D00",
        facts=[
            {"name": "Snapshot ID",    "value": snapshot_id},
            {"name": "Source Type",    "value": source_type},
            {"name": "Task ID",        "value": export_id},
            {"name": "S3 Bucket",      "value": BUCKET_NAME},
            {"name": "Days Remaining", "value": f"{days_remaining} day(s)"},
            {"name": "Deletion Date",  "value": scheduled_date},
            {"name": "Delay Setting",  "value": f"{DELETE_DELAY_DAYS} days"},
            {"name": "Note",           "value": "Snapshot exported to S3. Pending deletion after grace period."},
        ]
    )


def notify_deleted(export_id, snapshot_arn, deletion_info):
    """Post to the deleted channel after a snapshot is successfully removed."""
    snapshot_id = _extract_snapshot_id(snapshot_arn)
    source_type = deletion_info["source_type"]
    snap_label  = _snapshot_type_label(snapshot_arn)
    deleted_at  = deletion_info["deleted_at"]

    _post_to_teams(
        TEAMS_DELETED_WEBHOOK_URL,
        title=f"🗑️  {snap_label.title()} Snapshot — DELETED",
        color="9E9E9E",
        facts=[
            {"name": "Snapshot ID",  "value": snapshot_id},
            {"name": "Source Type",  "value": source_type},
            {"name": "Task ID",      "value": export_id},
            {"name": "S3 Bucket",    "value": BUCKET_NAME},
            {"name": "Deleted At",   "value": deleted_at},
            {"name": "Grace Period", "value": f"{DELETE_DELAY_DAYS} days (elapsed)"},
            {"name": "Note",         "value": "Data archived in S3. Source snapshot permanently deleted."},
        ]
    )


# ---------------------------------------------------------------------------
# SFN handler — called per-task by the Step Functions state machine
# ---------------------------------------------------------------------------

def sfn_handler(event, context):
    """
    Called by the Step Functions state machine for a single export task.
    The state machine passes the full RDS task object, snapshot ARN, and
    retry metadata. Returns {"outcome": "success|retry_required|max_retries_exhausted"}
    so the state machine Choice state can route accordingly.

    Expected event shape:
    {
      "task":           <full RDS ExportTask object from DescribeExportTasks>,
      "snapshot_arn":   "arn:aws:rds:...",
      "retry_count":    0,
      "max_retries":    5
    }
    """
    task          = event["task"]
    snapshot_arn  = event["snapshot_arn"]
    retry_count   = int(event.get("retry_count", 0))
    max_retries   = int(event.get("max_retries", MAX_RETRIES))

    status        = task["Status"]
    export_id     = task["ExportTaskIdentifier"]
    task_end_time = task.get("TaskEndTime")

    # Convert TaskEndTime string to datetime if needed
    if isinstance(task_end_time, str):
        try:
            task_end_time = datetime.fromisoformat(task_end_time.replace("Z", "+00:00"))
        except Exception:
            task_end_time = None

    if status == "COMPLETE":
        # --- Content validation ---
        try:
            integrity = check_integrity_for_export(task)
        except Exception as e:
            snapshot_identifier = _extract_snapshot_id(snapshot_arn)
            if retry_count < max_retries:
                notify_retry(
                    export_id, snapshot_arn, "INTEGRITY_FAILED",
                    attempt=retry_count + 1, max_retries=max_retries,
                    error=str(e), task=task
                )
                # Schedule retry via DynamoDB — maintenance pipeline starts a new SFN execution
                _schedule_retry(snapshot_arn, snapshot_identifier, retry_count)
                return {"outcome": "scheduled_retry", "error": str(e), "export_id": export_id}
            else:
                notify_failure(
                    export_id, snapshot_arn, "INTEGRITY_FAILED",
                    error=str(e), task=task,
                    retry_count=retry_count, max_retries=max_retries
                )
                _schedule_cleanup(task)
                return {"outcome": "max_retries_exhausted", "error": str(e), "export_id": export_id}

        # --- Success notification ---
        notify_success(export_id, snapshot_arn, task, integrity)

        # --- Schedule deletion via DynamoDB — maintenance pipeline handles it after the delay ---
        if DELETE_SOURCE_AFTER_EXPORT:
            scheduled_date = (task_end_time + timedelta(days=DELETE_DELAY_DAYS)).isoformat() if task_end_time else "N/A"
            deletion_info  = {
                "days_remaining":          DELETE_DELAY_DAYS,
                "scheduled_deletion_date": scheduled_date,
            }
            notify_pending_deletion(export_id, snapshot_arn, deletion_info)
            _schedule_deletion(snapshot_arn, export_id, task_end_time)

        return {"outcome": "success", "deletion": "scheduled", "export_id": export_id}

    elif status in ("FAILED", "CANCELED"):
        snapshot_identifier = _extract_snapshot_id(snapshot_arn)
        if retry_count < max_retries:
            notify_retry(
                export_id, snapshot_arn, status,
                attempt=retry_count + 1, max_retries=max_retries,
                task=task
            )
            # Schedule retry via DynamoDB — maintenance pipeline starts a new SFN execution.
            # This ends the current branch immediately so the Map state slot is freed.
            _schedule_retry(snapshot_arn, snapshot_identifier, retry_count)
            return {"outcome": "scheduled_retry", "export_id": export_id}
        else:
            notify_failure(
                export_id, snapshot_arn, status,
                task=task, retry_count=retry_count, max_retries=max_retries
            )
            # Schedule S3 cleanup via DynamoDB — maintenance pipeline handles it after the delay
            _schedule_cleanup(task)
            return {"outcome": "max_retries_exhausted", "export_id": export_id}

    return {"outcome": "skipped", "status": status, "export_id": export_id}


# ---------------------------------------------------------------------------
# Maintenance handler — called by the Maintenance SFN on its own schedule
# Processes overdue cleanup_pending and deletion_pending DynamoDB entries.
# ---------------------------------------------------------------------------

def maintenance_handler(event, context):
    """
    Process all pending work from DynamoDB:
      - cleanup_pending:  delete partial S3 objects from failed exports (after 1h delay)
      - deletion_pending: delete source RDS snapshots after the configured grace period
      - retry_pending:    start a new targeted Export SFN execution for failed snapshots

    Called by the Maintenance Step Functions state machine on a separate schedule,
    keeping the Export pipeline short-lived and free of inline waits and retry loops.
    """
    _process_pending_cleanups()
    _process_pending_deletions()
    _process_pending_retries(context)
    return {"status": "maintenance_complete"}


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def handler(event, context):
    # Route to maintenance handler when invoked by the Maintenance SFN
    if event.get("maintenance_mode"):
        return maintenance_handler(event, context)

    # Route to SFN handler when called by the Export state machine
    if SFN_MODE or "task" in event:
        return sfn_handler(event, context)

    # Invoke cleanup lambda for any pending cleanups whose delay has elapsed
    _process_pending_cleanups()

    tasks   = list_export_tasks()
    results = []

    for task in tasks:
        status        = task["Status"]
        export_id     = task["ExportTaskIdentifier"]
        snapshot_arn  = task["SourceArn"]
        task_end_time = task.get("TaskEndTime")

        terminal_key = f"export:{export_id}"   # set when task is fully resolved
        notif_key    = f"notif:{export_id}"    # set after success/failure notification
        pending_key  = f"pending:{export_id}"  # set after pending-deletion notification

        if status == "COMPLETE":
            if _is_task_processed(terminal_key):
                continue

            # --- Integrity check ---
            try:
                integrity = check_integrity_for_export(task)
            except Exception as e:
                retry_count = _get_retry_count(snapshot_arn)
                if retry_count < MAX_RETRIES:
                    attempt = _increment_retry_count(snapshot_arn)
                    _trigger_retry(snapshot_arn, _extract_snapshot_id(snapshot_arn), attempt)
                    notify_retry(
                        export_id, snapshot_arn, "INTEGRITY_FAILED",
                        attempt=attempt, max_retries=MAX_RETRIES,
                        error=str(e), task=task
                    )
                    results.append({
                        "export_task": export_id,
                        "status":      "INTEGRITY_FAILED",
                        "error":       str(e),
                        "action":      f"retry_triggered (attempt {attempt}/{MAX_RETRIES})",
                    })
                else:
                    # Max retries exhausted — schedule cleanup after delay, then notify
                    _schedule_cleanup(task)
                    if not _is_task_processed(notif_key):
                        notify_failure(
                            export_id, snapshot_arn, "INTEGRITY_FAILED",
                            error=str(e), task=task,
                            retry_count=retry_count, max_retries=MAX_RETRIES
                        )
                        _mark_task_processed(notif_key)
                    _mark_task_processed(terminal_key)
                    results.append({
                        "export_task": export_id,
                        "status":      "INTEGRITY_FAILED",
                        "error":       str(e),
                        "action":      "max_retries_exhausted",
                    })
                continue

            # --- Success notification (send once) ---
            if not _is_task_processed(notif_key):
                notify_success(export_id, snapshot_arn, task, integrity)
                _mark_task_processed(notif_key)

            # --- Deletion ---
            deletion_result = maybe_delete_snapshot(snapshot_arn, task_end_time)
            outcome = deletion_result["outcome"]

            if outcome == "pending":
                if not _is_task_processed(pending_key):
                    notify_pending_deletion(export_id, snapshot_arn, deletion_result)
                    _mark_task_processed(pending_key)
                results.append({
                    "export_task":    export_id,
                    "status":         "OK",
                    "deletion":       "pending",
                    "days_remaining": deletion_result["days_remaining"],
                })

            elif outcome == "deleted":
                notify_deleted(export_id, snapshot_arn, deletion_result)
                _mark_task_processed(terminal_key)
                results.append({"export_task": export_id, "status": "OK", "deletion": "deleted"})

            else:
                # skipped: flag_disabled | dry_run | no_end_time
                _mark_task_processed(terminal_key)
                results.append({
                    "export_task": export_id,
                    "status":      "OK",
                    "deletion":    f"skipped:{deletion_result.get('reason', '')}",
                })

        elif status in ("FAILED", "CANCELED"):
            if _is_task_processed(terminal_key):
                continue
            retry_count = _get_retry_count(snapshot_arn)
            if retry_count < MAX_RETRIES:
                attempt = _increment_retry_count(snapshot_arn)
                _trigger_retry(snapshot_arn, _extract_snapshot_id(snapshot_arn), attempt)
                notify_retry(
                    export_id, snapshot_arn, status,
                    attempt=attempt, max_retries=MAX_RETRIES,
                    task=task
                )
                _mark_task_processed(terminal_key)
                results.append({
                    "export_task": export_id,
                    "status":      status,
                    "action":      f"retry_triggered (attempt {attempt}/{MAX_RETRIES})",
                })
            else:
                # Max retries exhausted — schedule cleanup after delay, then notify
                _schedule_cleanup(task)
                notify_failure(
                    export_id, snapshot_arn, status,
                    task=task, retry_count=retry_count, max_retries=MAX_RETRIES
                )
                _mark_task_processed(terminal_key)
                results.append({
                    "export_task": export_id,
                    "status":      status,
                    "action":      "max_retries_exhausted",
                })

    return {"results": results}
