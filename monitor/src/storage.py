from __future__ import annotations

import os
import threading
import csv
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("monitor.storage")

# Configuration from env
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "monitor-events")
MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() in ("1", "true", "yes")
LOCAL_CSV_PATH = os.getenv("STORAGE_LOCAL_PATH", "/tmp/monitor_events.csv")
UPLOAD_INTERVAL_HOURS = float(os.getenv("UPLOAD_INTERVAL_HOURS", "6"))
# Storage disabled by default - enable only when properly configured
STORAGE_ENABLED = os.getenv("STORAGE_ENABLED", "true").lower() in ("1", "true", "yes")

_lock = threading.Lock()
_upload_timer = None
_storage_ok = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ensure_csv_exists(path: str) -> None:
    if not os.path.exists(path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["event_type", "timestamp", "details_json"])
        except Exception:
            logger.exception("_ensure_csv_exists: could not create file %s", path)


def _append_row_local(path: str, row: list) -> None:
    try:
        _ensure_csv_exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)
    except Exception:
        logger.exception("_append_row_local: failed to append row")


def _get_s3_client():
    try:
        import boto3
        from botocore.config import Config
    except Exception:
        logger.debug("boto3 not installed; S3 upload disabled")
        return None

    if not MINIO_ENDPOINT or not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
        logger.debug("MinIO config incomplete; S3 upload disabled")
        return None

    s3_conf = Config(signature_version="s3v4", region_name=MINIO_REGION)
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=("https://" if MINIO_USE_SSL else "http://") + MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            config=s3_conf,
        )
        return s3
    except Exception:
        logger.exception("_get_s3_client: failed to create S3 client")
        return None


def _upload_file_to_minio(path: str, key: Optional[str] = None) -> bool:
    s3 = _get_s3_client()
    if not s3:
        return False

    if key is None:
        # Build hierarchical key: YYYY/MM/DD/filename
        now = datetime.now(timezone.utc)
        filename = f"monitor_events_{now.strftime('%Y%m%d_%H%M')}.csv"
        key = f"{now.year}/{now.month:02d}/{now.day:02d}/{filename}"

    # ensure bucket exists (best-effort)
    try:
        s3.head_bucket(Bucket=MINIO_BUCKET)
    except Exception:
        try:
            s3.create_bucket(Bucket=MINIO_BUCKET)
        except Exception:
            logger.debug("_upload_file_to_minio: bucket may already exist or cannot be created")

    try:
        # Get file size for logging
        file_size = os.path.getsize(path)
        with open(path, "rb") as f:
            s3.put_object(Bucket=MINIO_BUCKET, Key=key, Body=f)
        logger.info("=== MinIO Upload Success ===")
        logger.info("File: %s", path)
        logger.info("Size: %d bytes", file_size)
        logger.info("Bucket: %s", MINIO_BUCKET)
        logger.info("Key: %s", key)
        logger.info("===========================")
        return True
    except Exception:
        logger.exception("=== MinIO Upload Failed ===")
        logger.error("File: %s", path)
        logger.error("Bucket: %s", MINIO_BUCKET)
        logger.error("Key: %s", key)
        logger.error("===========================")
        return False


def _append_and_maybe_upload(event_type: str, details: Dict[str, Any]) -> None:
    if not STORAGE_ENABLED:
        return
    row = [event_type, _now_iso(), json.dumps(details, default=str, ensure_ascii=False)]
    with _lock:
        _append_row_local(LOCAL_CSV_PATH, row)
        # Upload is handled by periodic timer, not on every write


def _periodic_upload():
    """Periodic upload function called by timer every UPLOAD_INTERVAL_HOURS"""
    global _upload_timer
    try:
        logger.info("_periodic_upload: starting scheduled upload to MinIO")
        _upload_file_to_minio(LOCAL_CSV_PATH)
    except Exception:
        logger.exception("_periodic_upload: upload attempt failed")
    finally:
        # Reschedule next upload
        _schedule_next_upload()


def _schedule_next_upload():
    """Schedule next upload timer"""
    global _upload_timer
    if _upload_timer:
        _upload_timer.cancel()
    interval_seconds = UPLOAD_INTERVAL_HOURS * 3600
    _upload_timer = threading.Timer(interval_seconds, _periodic_upload)
    _upload_timer.daemon = True
    _upload_timer.start()
    logger.info("_schedule_next_upload: next upload in %.1f hours", UPLOAD_INTERVAL_HOURS)


def _check_minio_connection():
    """Check MinIO connection at startup if configured"""
    global _storage_ok
    
    if not STORAGE_ENABLED:
        logger.info("=== Storage Configuration ===")
        logger.info("Storage: DISABLED via STORAGE_ENABLED=false")
        logger.info("===========================")
        _storage_ok = False
        return False
    
    logger.info("=== Storage Configuration ===")
    logger.info("Storage: ENABLED")
    logger.info("Local CSV path: %s", LOCAL_CSV_PATH)
    
    if not MINIO_ENDPOINT:
        logger.info("MinIO: NOT CONFIGURED (MINIO_ENDPOINT not set)")
        logger.info("Storage mode: LOCAL-ONLY")
        logger.info("===========================")
        _storage_ok = True  # local storage is OK
        return True
    
    logger.info("MinIO endpoint: %s", MINIO_ENDPOINT)
    logger.info("MinIO bucket: %s", MINIO_BUCKET)
    logger.info("MinIO region: %s", MINIO_REGION)
    logger.info("MinIO SSL: %s", MINIO_USE_SSL)
    logger.info("Upload interval: %.1f hours", UPLOAD_INTERVAL_HOURS)
    logger.info("Checking connection to MinIO...")
    
    s3 = _get_s3_client()
    if not s3:
        logger.error("FAILED: Could not create S3 client")
        logger.info("===========================")
        _storage_ok = False
        return False
    
    try:
        # Try to check if bucket exists
        s3.head_bucket(Bucket=MINIO_BUCKET)
        logger.info("SUCCESS: Bucket '%s' already exists and is accessible", MINIO_BUCKET)
        logger.info("Storage mode: LOCAL + MINIO UPLOAD")
        logger.info("===========================")
        _storage_ok = True
        return True
    except Exception as e:
        # Bucket doesn't exist, try to create it
        logger.info("Bucket '%s' not found, attempting to create...", MINIO_BUCKET)
        try:
            s3.create_bucket(Bucket=MINIO_BUCKET)
            logger.info("SUCCESS: Created new bucket '%s'", MINIO_BUCKET)
            logger.info("Storage mode: LOCAL + MINIO UPLOAD")
            logger.info("===========================")
            _storage_ok = True
            return True
        except Exception as create_err:
            logger.error("FAILED: Cannot access or create bucket '%s'", MINIO_BUCKET)
            logger.error("Error: %s", str(create_err)[:200])
            logger.info("===========================")
            _storage_ok = False
            return False


def is_storage_ready() -> bool:
    """Check if storage module is ready and functional"""
    return _storage_ok


def get_storage_status() -> Dict[str, Any]:
    """Return storage configuration and status for diagnostics"""
    return {
        "enabled": STORAGE_ENABLED,
        "ready": _storage_ok,
        "local_path": LOCAL_CSV_PATH if STORAGE_ENABLED else None,
        "minio_configured": bool(MINIO_ENDPOINT),
        "minio_endpoint": MINIO_ENDPOINT if MINIO_ENDPOINT else None,
        "minio_bucket": MINIO_BUCKET if MINIO_ENDPOINT else None,
        "upload_interval_hours": UPLOAD_INTERVAL_HOURS if STORAGE_ENABLED else None,
    }


# Check MinIO connection at startup
_check_minio_connection()

# Start periodic upload timer on module import (only if storage enabled and MinIO configured)
if STORAGE_ENABLED and MINIO_ENDPOINT:
    _schedule_next_upload()


def log_boiler_event(boiler_status: bool, info: Dict[str, Any]) -> None:
    """Log times when boiler_status is True (and also when it changes).

    info: extra metadata (e.g., module ids, firmware, etc.)
    """
    try:
        details = {"boiler_status": bool(boiler_status), "meta": info}
        _append_and_maybe_upload("boiler_status", details)
    except Exception:
        logger.exception("log_boiler_event failed")


def log_cycle_event(room_id: str, event: str, started_at: Optional[str], attempts: int, initial_temp: Optional[float], final_temp: Optional[float] = None, extra: Optional[Dict[str, Any]] = None) -> None:
    try:
        details = {
            "room_id": room_id,
            "event": event,
            "started_at": started_at,
            "attempts": attempts,
            "initial_temp": initial_temp,
            "final_temp": final_temp,
        }
        if extra:
            details["extra"] = extra
        _append_and_maybe_upload("cycle_event", details)
    except Exception:
        logger.exception("log_cycle_event failed")