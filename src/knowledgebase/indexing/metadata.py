"""
Metadata extraction for KnowledgeBase Engine.

Extracts metadata from documents based on file type and content.
"""

from __future__ import annotations


import re
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class MetadataExtractor:
    """
    Extracts metadata from documents based on content and file information.

    Supports extracting:
    - File metadata (path, size, timestamps)
    - Markdown frontmatter (YAML)
    - Code metadata (functions, classes)
    - Title extraction from content
    """

    # Patterns for metadata extraction
    MARKDOWN_TITLE_PATTERN = re.compile(r"^#\s+(\S.*)$", re.MULTILINE)
    YAML_FRONTMATTER_PATTERN = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*\n", re.DOTALL)
    PYTHON_DOCSTRING_PATTERN = re.compile(r'^"""(.+?)"""', re.DOTALL)
    CODE_FUNCTION_PATTERN = re.compile(r"^(?:def|function|func)\s+(\w+)", re.MULTILINE)
    CODE_CLASS_PATTERN = re.compile(r"^class\s+(\w+)", re.MULTILINE)

    # Language detection by extension
    LANGUAGE_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".xml": "xml",
        ".html": "html",
        ".css": "css",
        ".sql": "sql",
        ".sh": "shell",
        ".bash": "shell",
        ".ps1": "powershell",
    }

    def extract_from_file(self, file_path: str | Path) -> dict[str, Any]:
        """
        Extract metadata from a file.

        Args:
            file_path: Path to the file.

        Returns:
            dict: Extracted metadata.
        """
        path = Path(file_path)
        metadata: dict[str, Any] = {
            "path": str(path.absolute()),
            "filename": path.name,
            "extension": path.suffix.lower(),
            "source_type": "file",
        }

        # File system metadata
        if path.exists():
            stat = path.stat()
            metadata["size_bytes"] = stat.st_size
            metadata["created_at"] = datetime.fromtimestamp(stat.st_ctime).isoformat()
            metadata["updated_at"] = datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Language detection
        language = self.LANGUAGE_MAP.get(path.suffix.lower())
        if language:
            metadata["language"] = language

        return metadata

    def extract_from_content(
        self,
        content: str,
        file_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        Extract metadata from document content.

        Args:
            content: Document content.
            file_path: Optional file path for context.

        Returns:
            dict: Extracted metadata.
        """
        metadata: dict[str, Any] = {}

        # Get file metadata if path provided
        if file_path:
            metadata.update(self.extract_from_file(file_path))

        # Determine content type
        extension = metadata.get("extension", "")

        # Extract based on content type
        if extension in (".md", ".markdown"):
            metadata.update(self._extract_markdown_metadata(content))
        elif extension in (".py", ".js", ".ts", ".go", ".java", ".rb"):
            metadata.update(self._extract_code_metadata(content))

        # Extract title if not already found
        if "title" not in metadata:
            title = self._extract_title(content)
            if title:
                metadata["title"] = title

        return metadata

    def _extract_markdown_metadata(self, content: str) -> dict[str, Any]:
        """Extract metadata from Markdown content."""
        metadata: dict[str, Any] = {}

        # Try to extract YAML frontmatter
        frontmatter_match = self.YAML_FRONTMATTER_PATTERN.match(content)
        if frontmatter_match:
            try:
                # Simple YAML-like parsing (key: value format)
                frontmatter = frontmatter_match.group(1)
                for line in frontmatter.split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        key = key.strip().lower()
                        value = value.strip()
                        # Remove surrounding quotes if present
                        if (value.startswith('"') and value.endswith('"')) or (
                            value.startswith("'") and value.endswith("'")
                        ):
                            value = value[1:-1]
                        metadata[key] = value
            except Exception as e:
                logger.debug("Failed to parse frontmatter", error=str(e))

        # Extract title from first heading
        title_match = self.MARKDOWN_TITLE_PATTERN.search(content)
        if title_match and "title" not in metadata:
            metadata["title"] = title_match.group(1).strip()

        return metadata

    def _extract_code_metadata(self, content: str) -> dict[str, Any]:
        """Extract metadata from code content."""
        metadata: dict[str, Any] = {}

        # Extract docstring (for Python)
        docstring_match = self.PYTHON_DOCSTRING_PATTERN.match(content)
        if docstring_match:
            docstring = docstring_match.group(1).strip()
            # Use first line as description
            first_line = docstring.split("\n")[0].strip()
            if first_line:
                metadata["description"] = first_line

        # Extract function names
        functions = self.CODE_FUNCTION_PATTERN.findall(content)
        if functions:
            metadata["functions"] = functions[:10]  # Limit to first 10

        # Extract class names
        classes = self.CODE_CLASS_PATTERN.findall(content)
        if classes:
            metadata["classes"] = classes[:10]  # Limit to first 10

        return metadata

    def _extract_title(self, content: str) -> str | None:
        """
        Extract a title from content.

        Tries various strategies:
        1. First markdown heading
        2. First line if short enough
        3. First sentence

        Args:
            content: Document content.

        Returns:
            str | None: Extracted title or None.
        """
        # Try markdown heading
        match = self.MARKDOWN_TITLE_PATTERN.search(content)
        if match:
            return match.group(1).strip()

        # Try first line if short
        first_line = content.split("\n")[0].strip()
        if first_line and len(first_line) <= 100:
            return first_line

        # Try first sentence
        sentences = re.split(r"[.!?]\s", content, maxsplit=1)
        if sentences and len(sentences[0]) <= 150:
            return sentences[0].strip()

        return None


def extract_metadata(
    content: str,
    file_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Convenience function to extract metadata from content.

    Args:
        content: Document content.
        file_path: Optional file path.

    Returns:
        dict: Extracted metadata.
    """
    extractor = MetadataExtractor()
    return extractor.extract_from_content(content, file_path)
