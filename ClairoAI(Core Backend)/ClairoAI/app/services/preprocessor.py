"""
Input pre-processing pipeline.

Normalizes and cleans input data (diffs, commits, project files)
before sending to the LLM. Handles noise stripping, truncation,
and chunking for large inputs.
"""

import re
from typing import List, Dict

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.exceptions import InputValidationError

logger = get_logger("preprocessor")

# File extensions considered relevant for code analysis
RELEVANT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".md", ".txt", ".yml", ".yaml", ".toml",
    ".json", ".xml", ".html", ".css", ".scss", ".sql", ".sh",
    ".dockerfile", ".tf", ".proto",
}

# Patterns to strip from diffs (noise)
NOISE_PATTERNS = [
    r"^index [a-f0-9]+\.\.[a-f0-9]+ \d+$",  # git index lines
    r"^Binary files .+ differ$",               # binary file diffs
    r"^diff --git .+$",                         # diff headers (keep for context)
    r"^\\ No newline at end of file$",          # trailing newline markers
]


def preprocess_diff(raw_diff: str) -> str:
    """
    Clean and normalize a git diff for LLM consumption.

    - Strips binary file diffs
    - Removes noise lines
    - Normalizes whitespace
    - Truncates if over size limit
    """
    if not raw_diff or not raw_diff.strip():
        raise InputValidationError("Diff input is empty")

    lines = raw_diff.splitlines()
    cleaned_lines = []

    for line in lines:
        # Skip pure noise lines
        is_noise = False
        for pattern in NOISE_PATTERNS:
            if re.match(pattern, line):
                is_noise = True
                break

        if not is_noise:
            cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()

    if not cleaned:
        raise InputValidationError("Diff contains no meaningful content after cleaning")

    logger.info(
        "Diff preprocessed",
        extra={"extra_data": {
            "original_lines": len(lines),
            "cleaned_lines": len(cleaned_lines),
        }},
    )
    return cleaned


def preprocess_commit(commit_message: str) -> str:
    """
    Clean a commit message for summarization.

    Minimal processing — mainly whitespace normalization and
    validation that there's meaningful content.
    """
    if not commit_message or not commit_message.strip():
        raise InputValidationError("Commit message is empty")

    # Normalize whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", commit_message.strip())
    return cleaned


def preprocess_project_files(file_contents: Dict[str, str]) -> str:
    """
    Convert extracted project files into a single LLM-friendly string.

    - Filters to relevant file types
    - Adds file path markers for context
    - Respects token budget (truncates per file if needed)
    """
    settings = get_settings()
    max_total_chars = settings.CHUNK_SIZE_CHARS * 3  # Allow up to 3 chunks worth

    if not file_contents:
        raise InputValidationError("No files provided from project upload")

    output_parts = []
    total_chars = 0
    files_included = 0

    # Sort files by path for deterministic output
    for filepath in sorted(file_contents.keys()):
        content = file_contents[filepath]

        # Check file extension relevance
        ext = "." + filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
        if ext and ext not in RELEVANT_EXTENSIONS:
            continue

        # Skip empty files
        if not content.strip():
            continue

        # Truncate individual files if needed
        max_per_file = 5000  # chars per file
        if len(content) > max_per_file:
            content = content[:max_per_file] + "\n... [truncated]"

        file_block = f"\n--- FILE: {filepath} ---\n{content}\n"

        if total_chars + len(file_block) > max_total_chars:
            logger.info(
                f"Stopping file inclusion at {files_included} files (token budget)"
            )
            break

        output_parts.append(file_block)
        total_chars += len(file_block)
        files_included += 1

    if not output_parts:
        raise InputValidationError("No relevant source files found in project")

    result = "\n".join(output_parts)
    logger.info(
        "Project files preprocessed",
        extra={"extra_data": {
            "files_included": files_included,
            "total_chars": total_chars,
        }},
    )
    return result


def chunk_text(text: str, chunk_size: int | None = None) -> List[str]:
    """
    Split text into chunks for batched LLM processing.

    Attempts to split at line boundaries to keep diff hunks intact.
    Returns a list of chunks, each under the size limit.
    """
    settings = get_settings()
    size = chunk_size or settings.CHUNK_SIZE_CHARS

    if len(text) <= size:
        return [text]

    chunks = []
    lines = text.splitlines(keepends=True)
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) > size and current_chunk:
            chunks.append(current_chunk.rstrip())
            current_chunk = line
        else:
            current_chunk += line

    if current_chunk.strip():
        chunks.append(current_chunk.rstrip())

    logger.info(f"Text split into {len(chunks)} chunks")
    return chunks
