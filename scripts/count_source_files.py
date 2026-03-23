"""
Count source files in the current Git repository.

Usage:
    python scripts/count_source_files.py
    Or from repo root: uv run python scripts/count_source_files.py
"""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Programming language extensions (for "code-only" count)
CODE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".vue",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".php",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".swift",
        ".scala",
        ".r",
        ".sh",
    }
)

# Common source extensions and their human-readable names
EXTENSION_NAMES: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".js": "JavaScript",
    ".jsx": "JavaScript React",
    ".vue": "Vue",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ header",
    ".hpp": "C++ header",
    ".swift": "Swift",
    ".scala": "Scala",
    ".r": "R",
    ".sql": "SQL",
    ".sh": "Shell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
    ".md": "Markdown",
}


def get_tracked_files(repo_root: Path) -> list[str]:
    """Get tracked files via git ls-files (respects .gitignore)."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines() if result.stdout.strip() else []


def count_by_extension(files: list[str]) -> tuple[dict[str, int], list[str]]:
    """
    Count files by extension.

    Returns:
        (extension -> count dict, list of unrecognized extensions)
    """
    counts: dict[str, int] = defaultdict(int)
    unknown: list[str] = []

    for filepath in files:
        path = Path(filepath)
        ext = path.suffix.lower()

        if not ext:
            continue

        if ext in EXTENSION_NAMES:
            counts[ext] += 1
        else:
            # Only count extensions that look like source (alpha chars)
            if ext[1:].isalpha() and len(ext) <= 6:
                counts[ext] = counts.get(ext, 0) + 1
                if ext not in [e for e in EXTENSION_NAMES]:
                    unknown.append(ext)

    return dict(counts), list(dict.fromkeys(unknown))


WIDTH = 100
INNER = WIDTH - 2  # Space between │ borders


def _pad(content: str, width: int = INNER) -> str:
    """Pad content to exact width for fixed-line alignment."""
    return content[:width].ljust(width)


def format_output(counts: dict[str, int], total: int, repo_root: Path) -> str:
    """Format human-readable statistics output with fixed 100-char width."""
    lines: list[str] = []
    sep = "┌" + "─" * INNER + "┐"
    div = "├" + "─" * INNER + "┤"
    end = "└" + "─" * INNER + "┘"

    lines.append("")
    lines.append(sep)
    lines.append("│" + _pad("  Repository Source Stats") + "│")
    lines.append(div)

    # Sort by count descending
    sorted_items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    lines.append("│" + _pad("  Ext         Language/Type      Count    Pct") + "│")
    lines.append(div)

    for ext, count in sorted_items:
        lang = EXTENSION_NAMES.get(ext, ext)
        pct = (count / total * 100) if total > 0 else 0
        bar_len = min(20, int(pct / 5))  # Simple bar chart, max 20 cells
        bar = "█" * bar_len + "░" * (20 - bar_len)
        row = f"  {ext:<10}  {lang:<16}  {count:>5}    {pct:>5.1f}%  {bar}"
        lines.append("│" + _pad(row) + "│")

    code_total = sum(c for e, c in counts.items() if e in CODE_EXTENSIONS)
    lines.append(div)
    summary = f"  Total: {total} files | Code: {code_total} files"
    lines.append("│" + _pad(summary) + "│")
    lines.append(end)
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    repo_root = Path(__file__).resolve().parent.parent

    if not (repo_root / ".git").exists():
        print("Error: not a Git repository root.", file=sys.stderr)
        return 1

    files = get_tracked_files(repo_root)
    counts, _ = count_by_extension(files)
    total = sum(counts.values())

    if total == 0:
        print("No source files found.")
        return 0

    print(format_output(counts, total, repo_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
