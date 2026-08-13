# app/modules/media/s3.py
import uuid

import boto3

from botocore.client import Config
from app.config import settings


def get_s3_client():
    return boto3.client(
        "s3", 
        region_name=settings.aws_region,
        config=Config(signature_version="s3v4"),
    )


def generate_upload_url(
    tenant_id: str,
    inspection_id: str,
    finding_id: str,
    content_type: str,
) -> dict:
    """Generate presigned PUT URL for direct browser upload to S3."""
    photo_id = str(uuid.uuid4())
    ext = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/heic": "heic",
        "image/webp": "webp",
    }.get(content_type, "jpg")
    key = (
        f"tenants/{tenant_id}/inspections/{inspection_id}"
        f"/findings/{finding_id}/{photo_id}.{ext}"
    )

    client = get_s3_client()
    upload_url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.media_bucket,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=900,  # 15 minutes to complete upload
    )
    view_url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.media_bucket, "Key": key},
        ExpiresIn=86400,  # 24 hours for viewing
    )

    return {
        "upload_url": upload_url,
        "view_url": view_url,
        "key": key,
        "photo_id": photo_id,
    }


def generate_view_url(key: str) -> str:
    """Generate 24h presigned GET URL for an existing S3 object."""
    client = get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.media_bucket, "Key": key},
        ExpiresIn=86400,
    )
