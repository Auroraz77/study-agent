from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from minio import Minio

from app import config


class MinioStorage:
    def __init__(self) -> None:
        self.bucket = config.MINIO_BUCKET
        self.client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_SECURE,
        )

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def upload_course_file(
        self,
        filename: str,
        data: bytes,
        content_type: str | None,
        course: str = "default",
    ) -> dict[str, Any]:
        self.ensure_bucket()
        safe_filename = Path(filename or "uploaded-file").name
        safe_course = _safe_path_part(course)
        today = datetime.now().strftime("%Y%m%d")
        object_name = f"course-files/raw/{safe_course}/{today}/{uuid4().hex}-{safe_filename}"

        self.client.put_object(
            bucket_name=self.bucket,
            object_name=object_name,
            data=BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )

        return {
            "bucket": self.bucket,
            "object_name": object_name,
            "storage_url": f"minio://{self.bucket}/{object_name}",
            "size": len(data),
            "content_type": content_type or "application/octet-stream",
        }

    def read_object(self, object_name: str, bucket: str | None = None) -> bytes:
        response = self.client.get_object(bucket or self.bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


def _safe_path_part(value: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in ("-", "_") else "-"
        for char in (value or "default").strip()
    )
    return cleaned.strip("-") or "default"
