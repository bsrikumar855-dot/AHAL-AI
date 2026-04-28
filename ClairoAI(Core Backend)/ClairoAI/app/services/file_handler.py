"""
File upload handler for .zip project uploads.

Safely extracts, filters, and converts project files into
LLM-friendly input. Includes protection against path traversal,
oversized files, and irrelevant content.
"""

import os
import zipfile
import shutil
import tempfile
from pathlib import Path
from typing import Dict

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.exceptions import FileProcessingError

logger = get_logger("file_handler")

# Directories to skip during extraction
SKIP_DIRECTORIES = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "env", ".env", "dist", "build", ".next", ".cache",
    ".idea", ".vscode", "vendor", "target", "bin", "obj",
    ".tox", ".mypy_cache", ".pytest_cache", "coverage",
}

# File extensions to include
INCLUDE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".md", ".txt", ".yml", ".yaml", ".toml",
    ".json", ".xml", ".html", ".css", ".scss", ".sql", ".sh",
    ".dockerfile", ".tf", ".proto", ".graphql", ".prisma",
}


class FileHandler:
    """
    Handles .zip file uploads securely.

    Extracts files, filters for relevance, and returns
    a dict of {relative_path: file_content} suitable for
    the preprocessing pipeline.
    """

    def __init__(self):
        self.settings = get_settings()

    async def process_upload(self, file_bytes: bytes, filename: str) -> Dict[str, str]:
        """
        Process an uploaded .zip file.

        Args:
            file_bytes: Raw bytes of the uploaded file
            filename:   Original filename

        Returns:
            Dict mapping relative file paths to their text content.

        Raises:
            FileProcessingError: On invalid file, extraction failure, etc.
        """
        # Validate file
        self._validate_upload(file_bytes, filename)

        # Create temp directory for extraction
        temp_dir = tempfile.mkdtemp(prefix="contextbridge_")

        try:
            # Extract safely
            zip_path = os.path.join(temp_dir, "upload.zip")
            with open(zip_path, "wb") as f:
                f.write(file_bytes)

            extract_dir = os.path.join(temp_dir, "extracted")
            self._safe_extract(zip_path, extract_dir)

            # Collect relevant files
            file_contents = self._collect_files(extract_dir)

            print("==== FILE DEBUG START ====")
            print(f"TOTAL FILES EXTRACTED: {len(file_contents)}")

            for path, content in file_contents.items():
                print(f"{path} -> SIZE: {len(content)}")

            print("==== FILE DEBUG END ====")

            valid_ext = (".py", ".js", ".ts", ".json", ".md")

            file_contents = {
                path: content
                for path, content in file_contents.items()
                if path.endswith(valid_ext) and content and len(content.strip()) > 30
            }

            print(f"FILES AFTER FILTER: {len(file_contents)}")

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
        except Exception as e:
            logger.error(f"Upload processing failed: {e}")
            raise FileProcessingError(f"Failed to process upload: {str(e)}")
        finally:
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _validate_upload(self, file_bytes: bytes, filename: str) -> None:
        """Validate the uploaded file before processing."""
        if not filename.lower().endswith(".zip"):
            raise FileProcessingError("Only .zip files are supported")

        max_size = self.settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_size:
            raise FileProcessingError(
                f"File exceeds maximum size of {self.settings.MAX_UPLOAD_SIZE_MB}MB"
            )

        if len(file_bytes) == 0:
            raise FileProcessingError("Uploaded file is empty")

        # Verify it's a valid zip
        try:
            import io
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                if zf.testzip() is not None:
                    raise FileProcessingError("Uploaded file is a corrupted ZIP")
        except zipfile.BadZipFile:
            raise FileProcessingError("Uploaded file is not a valid ZIP archive")

    def _safe_extract(self, zip_path: str, extract_dir: str) -> None:
        """
        Extract ZIP file with path traversal protection.

        Validates each member name to prevent directory escape attacks.
        """
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                # Path traversal protection
                member_path = Path(extract_dir) / member
                try:
                    member_path.resolve().relative_to(Path(extract_dir).resolve())
                except ValueError:
                    logger.warning(f"Skipping suspicious path: {member}")
                    continue

                # Skip directories in the skip list
                parts = Path(member).parts
                if any(part in SKIP_DIRECTORIES for part in parts):
                    continue

                zf.extract(member, extract_dir)

    # Extensions that are always binary — never attempt to read
    _BINARY_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
        ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
        ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe", ".bin",
        ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z",
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".sqlite", ".db", ".lock",
    }

    def _collect_files(self, extract_dir: str) -> Dict[str, str]:
        """
        Walk the extracted directory and collect relevant file contents.

        Filters by extension and size. Returns relative paths
        as keys for clarity in the LLM prompt.
        """
        max_file_size = self.settings.MAX_FILE_SIZE_KB * 1024
        file_contents: Dict[str, str] = {}
        extract_path = Path(extract_dir)
        skipped_empty = 0
        skipped_binary = 0
        skipped_ext = 0

        for file_path in extract_path.rglob("*"):
            if not file_path.is_file():
                continue

            # Check extension
            suffix = file_path.suffix.lower()
            name = file_path.name.lower()

            # Skip known binary extensions
            if suffix in self._BINARY_EXTENSIONS:
                skipped_binary += 1
                continue

            # Include only known code/text extensions or special filenames
            if suffix not in INCLUDE_EXTENSIONS and name not in {
                "dockerfile", "makefile", "rakefile", "gemfile",
                "procfile", "brewfile", ".gitignore", ".dockerignore",
            }:
                skipped_ext += 1
                continue

            # Check file size on disk
            try:
                file_size = file_path.stat().st_size
            except OSError:
                continue

            if file_size > max_file_size:
                logger.info(f"Skipping oversized file: {file_path.name} ({file_size} bytes)")
                continue

            if file_size == 0:
                skipped_empty += 1
                continue

            # Read file content safely — NEVER fail on encoding
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {file_path.name}: {e}")
                continue

            # Strip and validate content
            content = content.strip()

            # Skip empty or too-small files
            if not content or len(content) < 20:
                skipped_empty += 1
                continue

            # Skip files that look binary (contain null bytes)
            if "\x00" in content:
                skipped_binary += 1
                continue

            # Use relative path as key
            rel_path = str(file_path.relative_to(extract_path))
            file_contents[rel_path] = content

        # Debug logging — print to stdout for immediate visibility
        print(f"TOTAL EXTRACTED FILES: {len(file_contents)}")
        print(f"SKIPPED: {skipped_empty} empty, {skipped_binary} binary, {skipped_ext} wrong ext")

        for path, content in list(file_contents.items())[:15]:
            print(f"  FILE: {path} SIZE: {len(content)}")

        logger.info(
            f"Collected {len(file_contents)} files "
            f"(skipped: {skipped_empty} empty, {skipped_binary} binary, {skipped_ext} ext)"
        )

        return file_contents

