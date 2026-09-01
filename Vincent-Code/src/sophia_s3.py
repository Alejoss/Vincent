"""Download Sophia media objects from S3 via AWS CLI (or boto3 fallback)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_bucket(explicit: Optional[str] = None) -> str:
    bucket = (
        explicit
        or os.getenv("AWS_STORAGE_BUCKET_NAME")
        or os.getenv("SOPHIA_S3_BUCKET")
        or ""
    ).strip()
    if not bucket:
        raise ValueError(
            "AWS_STORAGE_BUCKET_NAME (or SOPHIA_S3_BUCKET) is required for S3 downloads"
        )
    return bucket


def resolve_region(explicit: Optional[str] = None) -> Optional[str]:
    return (
        explicit
        or os.getenv("AWS_S3_REGION_NAME")
        or os.getenv("AWS_DEFAULT_REGION")
        or ""
    ).strip() or None


def download_s3_object(
    file_key: str,
    dest_path: str | Path,
    *,
    bucket: Optional[str] = None,
    region: Optional[str] = None,
) -> Path:
    """
    Download s3://bucket/file_key to dest_path.

    Prefers AWS CLI (`aws s3 cp`) when available; falls back to boto3.
    """
    key = (file_key or "").lstrip("/")
    if not key:
        raise ValueError("file_key is empty")

    bucket_name = resolve_bucket(bucket)
    region_name = resolve_region(region)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.is_file() and dest.stat().st_size > 0:
        logger.info("S3 cache hit: %s", dest)
        return dest

    uri = f"s3://{bucket_name}/{key}"
    aws = shutil.which("aws")
    if aws:
        cmd = [aws, "s3", "cp", uri, str(dest)]
        if region_name:
            cmd.extend(["--region", region_name])
        logger.info("Downloading %s → %s", uri, dest)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()[:800]
            raise RuntimeError(f"aws s3 cp failed ({result.returncode}): {err}")
        if not dest.is_file() or dest.stat().st_size == 0:
            raise RuntimeError(f"Download produced empty file: {dest}")
        return dest

    try:
        import boto3  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Neither AWS CLI nor boto3 is available for S3 download"
        ) from exc

    logger.info("Downloading via boto3 %s → %s", uri, dest)
    client_kwargs = {}
    if region_name:
        client_kwargs["region_name"] = region_name
    client = boto3.client("s3", **client_kwargs)
    client.download_file(bucket_name, key, str(dest))
    if not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError(f"Download produced empty file: {dest}")
    return dest


def head_s3_object(
    file_key: str,
    *,
    bucket: Optional[str] = None,
    region: Optional[str] = None,
) -> bool:
    """Return True if object exists (best-effort via aws s3api head-object)."""
    key = (file_key or "").lstrip("/")
    bucket_name = resolve_bucket(bucket)
    region_name = resolve_region(region)
    aws = shutil.which("aws")
    if not aws:
        return True  # skip probe; download will fail later if missing
    cmd = [
        aws,
        "s3api",
        "head-object",
        "--bucket",
        bucket_name,
        "--key",
        key,
    ]
    if region_name:
        cmd.extend(["--region", region_name])
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0
