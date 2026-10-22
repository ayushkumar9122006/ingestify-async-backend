import os
import shutil
import mimetypes
from typing import Tuple
from fastapi import UploadFile
from app.core.config import settings


class FileService:
    @staticmethod
    def ensure_directories() -> None:
        """Ensure all storage directories exist."""
        for path in [settings.UPLOAD_DIR, settings.ARTIFACT_DIR, settings.THUMBNAIL_DIR]:
            os.makedirs(path, exist_ok=True)

    @classmethod
    async def save_uploaded_file(cls, job_id: str, upload_file: UploadFile) -> Tuple[str, int, str]:
        """
        Saves an uploaded FastAPI file stream to disk.
        Returns: (file_path, file_size_bytes, mime_type)
        """
        cls.ensure_directories()
        safe_filename = upload_file.filename or f"upload_{job_id}.bin"
        file_path = os.path.join(settings.UPLOAD_DIR, f"{job_id}_{safe_filename}")

        bytes_written = 0
        with open(file_path, "wb") as buffer:
            while chunk := await upload_file.read(1024 * 64):  # 64KB chunks
                bytes_written += len(chunk)
                buffer.write(chunk)

        # Detect or refine MIME type
        content_type = upload_file.content_type
        if not content_type or content_type == "application/octet-stream":
            guessed_type, _ = mimetypes.guess_type(safe_filename)
            content_type = guessed_type or "application/octet-stream"

        return file_path, bytes_written, content_type

    @staticmethod
    def remove_file(file_path: str) -> None:
        """Safely remove a file from disk if present."""
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


file_service = FileService()
