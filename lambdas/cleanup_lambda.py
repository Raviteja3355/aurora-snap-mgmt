import os
import boto3

s3 = boto3.client("s3")

BUCKET_NAME  = os.environ["BUCKET_NAME"]
DRY_RUN_MODE = os.environ.get("DRY_RUN_MODE", "false").lower() == "true"


def _list_objects(prefix):
    objs      = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []):
            objs.append(obj)
    return objs


def handler(event, context):
    """
    Delete partial S3 objects left behind by a failed or canceled RDS export task.

    RDS writes all export files under {S3Prefix}/{ExportTaskIdentifier}/ within the bucket.
    This function targets only that specific task prefix — it does not touch other exports
    for the same snapshot.

    Expected event shape:
    {
      "task": {
        "ExportTaskIdentifier": "exp-...",
        "S3Prefix": "snapshots/my-snapshot"
      }
    }
    """
    task      = event["task"]
    s3_prefix = task.get("S3Prefix", "").rstrip("/")
    export_id = task["ExportTaskIdentifier"]
    prefix    = f"{s3_prefix}/{export_id}/" if s3_prefix else f"{export_id}/"

    objs = _list_objects(prefix)
    if not objs:
        print(f"No objects found under s3://{BUCKET_NAME}/{prefix} — nothing to clean up")
        return {"prefix": prefix, "deleted_count": 0}

    if DRY_RUN_MODE:
        print(f"[DRY RUN] Would delete {len(objs)} objects under s3://{BUCKET_NAME}/{prefix}")
        return {"prefix": prefix, "deleted_count": 0, "dry_run": True}

    keys    = [{"Key": o["Key"]} for o in objs]
    deleted = 0
    for i in range(0, len(keys), 1000):
        s3.delete_objects(
            Bucket=BUCKET_NAME,
            Delete={"Objects": keys[i:i + 1000], "Quiet": True}
        )
        deleted += len(keys[i:i + 1000])

    print(f"Deleted {deleted} objects under s3://{BUCKET_NAME}/{prefix}")
    return {"prefix": prefix, "deleted_count": deleted}
