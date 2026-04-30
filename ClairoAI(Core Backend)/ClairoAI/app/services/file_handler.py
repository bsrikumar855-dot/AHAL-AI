"""
File upload handler for .zip project uploads.
"""

import asyncio
import gc
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Dict

from app.core.config import get_settings
from app.core.exceptions import FileProcessingError
from app.core.logging import get_logger

logger = get_logger("file_handler")

SKIP_DIRECTORIES = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "env", ".env", "dist", "build", ".next", ".cache",
    ".idea", ".vscode", "vendor", "target", "bin", "obj",
    ".tox", ".mypy_cache", ".pytest_cache", "coverage",
}


class FileHandler:
    _BINARY_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
        ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
        ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe", ".bin",
        ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z",
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".sqlite", ".db", ".lock",
    }

    def __init__(self):
        self.settings = get_settings()

    def _is_windows_lock_error(self, error: Exception) -> bool:
        return isinstance(error, PermissionError) or getattr(error, "winerror", None) == 32

    def _safe_delete(self, path: str) -> None:
        if not path:
            return
        for attempt in range(1, 4):
            if not os.path.exists(path):
                return
            try:
                logger.info("Deleting temp file", extra={"extra_data": {"path": path, "attempt": attempt}})
                os.remove(path)
                return
            except Exception as exc:
                logger.warning(
                    "Temp file delete failed",
                    extra={"extra_data": {"path": path, "attempt": attempt, "error": str(exc)}},
                )
                if attempt >= 3 or not self._is_windows_lock_error(exc):
                    return
                time.sleep(0.75 * attempt)

    def _safe_rmtree(self, path: str) -> None:
        if not path:
            return
        for attempt in range(1, 4):
            if not os.path.exists(path):
                return
            try:
                logger.info("Removing temp directory", extra={"extra_data": {"path": path, "attempt": attempt}})
                time.sleep(0.5)
                shutil.rmtree(path, ignore_errors=True)
                if not os.path.exists(path):
                    return
            except Exception as exc:
                logger.warning(
                    "Temp directory cleanup failed",
                    extra={"extra_data": {"path": path, "attempt": attempt, "error": str(exc)}},
                )
                if attempt >= 3 or not self._is_windows_lock_error(exc):
                    return
            time.sleep(0.75 * attempt)

    async def process_upload(self, file_bytes: bytes, filename: str) -> Dict[str, str]:
        return await asyncio.to_thread(self._process_upload_sync, file_bytes, filename)

    def _process_upload_sync(self, file_bytes: bytes, filename: str) -> Dict[str, str]:
        self._validate_upload(file_bytes, filename)
        temp_dir = tempfile.mkdtemp(prefix="contextbridge_")
        zip_path = os.path.join(temp_dir, f"{uuid.uuid4().hex}.zip")
        extract_dir = os.path.join(temp_dir, f"extract_{uuid.uuid4().hex}")
        logger.info(
            "Created upload temp paths",
            extra={"extra_data": {"filename": filename, "temp_dir": temp_dir, "zip_path": zip_path, "extract_dir": extract_dir}},
        )

        try:
            with open(zip_path, "wb") as file_handle:
                file_handle.write(file_bytes)

            self._safe_extract(zip_path, extract_dir)
            gc.collect()
            time.sleep(0.5)
            self._safe_delete(zip_path)

            file_contents = self._collect_files(extract_dir)
            if not file_contents:
                file_contents = self._collect_first_available_text_files(extract_dir, limit=10)

            logger.info(
                "Upload processed",
                extra={"extra_data": {
                    "filename": filename,
                    "files_extracted": len(file_contents),
                }},
            )
            return file_contents
        except FileProcessingError:
            raise
        except Exception as error:
            logger.error(f"Upload processing failed: {error}")
            raise FileProcessingError(f"Failed to process upload: {str(error)}")
        finally:
            self._safe_delete(zip_path)
            self._safe_rmtree(extract_dir)
            self._safe_rmtree(temp_dir)

    def _validate_upload(self, file_bytes: bytes, filename: str) -> None:
        if not filename.lower().endswith(".zip"):
            raise FileProcessingError("Only .zip files are supported")

        max_size = self.settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_size:
            raise FileProcessingError(
                f"File exceeds maximum size of {self.settings.MAX_UPLOAD_SIZE_MB}MB"
            )

        if len(file_bytes) == 0:
            raise FileProcessingError("Uploaded file is empty")

        try:
            import io
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zip_file:
                if zip_file.testzip() is not None:
                    raise FileProcessingError("Uploaded file is a corrupted ZIP")
        except zipfile.BadZipFile:
            raise FileProcessingError("Uploaded file is not a valid ZIP archive")

    def _safe_extract(self, zip_path: str, extract_dir: str) -> None:
        os.makedirs(extract_dir, exist_ok=True)
        logger.info("Extracting upload archive", extra={"extra_data": {"zip_path": zip_path, "extract_dir": extract_dir}})
        for attempt in range(1, 4):
            try:
                with zipfile.ZipFile(zip_path, "r") as zip_file:
                    for member in zip_file.namelist():
                        member_path = Path(extract_dir) / member
                        try:
                            member_path.resolve().relative_to(Path(extract_dir).resolve())
                        except ValueError:
                            logger.warning(f"Skipping suspicious path: {member}")
                            continue

                        parts = Path(member).parts
                        if any(part in SKIP_DIRECTORIES for part in parts):
                            continue

                        zip_file.extract(member, extract_dir)
                gc.collect()
                time.sleep(0.5)
                return
            except Exception as exc:
                logger.warning(
                    "Upload extraction attempt failed",
                    extra={"extra_data": {"zip_path": zip_path, "extract_dir": extract_dir, "attempt": attempt, "error": str(exc)}},
                )
                if attempt >= 3 or not self._is_windows_lock_error(exc):
                    raise
                time.sleep(1.0 * attempt)

    def _collect_files(self, extract_dir: str) -> Dict[str, str]:
        file_contents: Dict[str, str] = {}
        extract_path = Path(extract_dir)
        skipped_empty = 0
        skipped_binary = 0

        for file_path in extract_path.rglob("*"):
            if not file_path.is_file():
                continue

            if any(part in SKIP_DIRECTORIES for part in file_path.parts):
                continue

            suffix = file_path.suffix.lower()
            if suffix in self._BINARY_EXTENSIONS:
                skipped_binary += 1
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if "\x00" in content:
                skipped_binary += 1
                continue

            content = content.strip()
            if not content:
                skipped_empty += 1
                continue

            rel_path = str(file_path.relative_to(extract_path)).replace("\\", "/")
            file_contents[rel_path] = content

        logger.info(
            f"Collected {len(file_contents)} files "
            f"(skipped: {skipped_empty} empty, {skipped_binary} binary)"
        )
        return file_contents

    def _collect_first_available_text_files(self, extract_dir: str, limit: int = 10) -> Dict[str, str]:
        fallback_files: Dict[str, str] = {}
        extract_path = Path(extract_dir)

        for file_path in extract_path.rglob("*"):
            if len(fallback_files) >= limit:
                break
            if not file_path.is_file():
                continue
            if any(part in SKIP_DIRECTORIES for part in file_path.parts):
                continue

            suffix = file_path.suffix.lower()
            if suffix in self._BINARY_EXTENSIONS:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if "\x00" in content:
                continue

            content = content.strip()
            if not content:
                continue

            rel_path = str(file_path.relative_to(extract_path)).replace("\\", "/")
            fallback_files[rel_path] = content

        return fallback_files
