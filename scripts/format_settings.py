"""
Format Optimized Settings TOML Files

Normalizes every .toml file in the settings folder to a consistent style
modelled after `settings/4D5309C9.toml`:

- CRLF line endings
- No trailing newline at end of file
- Header is exactly two lines: `# Title Name: ...` then `# Title ID: ...`
- One blank line between header and first section
- Sections appear in the canonical xenia config order
- One blank line between sections
- Each option line: `key = value # comment` (single space around `=`,
  exactly one space before `#`)

By default, files are rewritten in place. Use `--check` for a dry run that
exits non-zero when any file would change (CI-friendly).

Comments, option values, option keys, and the set of options in a file are
preserved verbatim. Only spacing, line endings, and section ordering change.
"""

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _toml_utils import (
    ConfigFile,
    ConfigOption,
    ConfigSection,
    format_value,
)

# =========================
# Logging
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# =========================
# Constants
# =========================

CRLF = b"\r\n"
DEFAULT_SETTINGS_DIR = "settings"


# =========================
# Result tracking
# =========================


@dataclass
class FileResult:
    path: Path
    changed: bool
    skipped: bool = False
    reason: Optional[str] = None


# =========================
# Header validation
# =========================


class HeaderError(Exception):
    pass


def validate_header(config: ConfigFile) -> None:
    if not config.header_comment:
        raise HeaderError("missing header (expected '# Title Name:' and '# Title ID:')")

    has_name = False
    has_id = False

    for line in config.header_comment.split("\n"):
        if re.match(r"^\s*Title\s*Name\s*:", line, re.IGNORECASE):
            has_name = True
        if re.match(r"^\s*Title\s*ID\s*:", line, re.IGNORECASE):
            has_id = True

    if not has_name:
        raise HeaderError("missing '# Title Name:' line in header")
    if not has_id:
        raise HeaderError("missing '# Title ID:' line in header")


# =========================
# Canonical section ordering
# =========================


def canonical_section_order(xenia_config: ConfigFile) -> List[str]:
    return [s.name for s in xenia_config.sections]


def sort_sections(
    sections: List[ConfigSection],
    xenia_order: List[str],
) -> List[ConfigSection]:
    rank = {name: i for i, name in enumerate(xenia_order)}
    fallback = len(xenia_order)

    def key(section: ConfigSection) -> tuple:
        return (rank.get(section.name, fallback),)

    return sorted(sections, key=key)


# =========================
# Rendering
# =========================


def render_header(config: ConfigFile) -> str:
    if not config.header_comment:
        return ""
    lines = [line for line in config.header_comment.split("\n") if line.strip()]
    return "\r\n".join(f"# {line}" for line in lines)


def render_option_line(option: ConfigOption) -> str:
    value_text = format_value(option.value, option.type)
    base = f"{option.name} = {value_text}"
    if option.comment:
        return f"{base} # {option.comment}"
    return base


def render_document(config: ConfigFile, xenia_order: Optional[List[str]]) -> bytes:
    if xenia_order is None:
        sections = list(config.sections)
    else:
        sections = sort_sections(list(config.sections), xenia_order)

    parts: List[str] = []
    parts.append(render_header(config))

    if sections:
        parts.append("")
        for idx, section in enumerate(sections):
            parts.append(f"[{section.name}]")
            for option in section.options:
                parts.append(render_option_line(option))
            if idx != len(sections) - 1:
                parts.append("")

    text = "\r\n".join(parts)
    return text.encode("utf-8")


# =========================
# Per-file processing
# =========================


def process_file(
    path: Path,
    xenia_order: Optional[List[str]],
    check_only: bool,
) -> FileResult:
    try:
        original_bytes = path.read_bytes()
    except OSError as e:
        return FileResult(path, changed=False, skipped=True, reason=f"read error: {e}")

    try:
        text = original_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        return FileResult(
            path, changed=False, skipped=True, reason=f"utf-8 decode error: {e}"
        )

    try:
        config = ConfigFile.from_string(text)
    except Exception as e:
        return FileResult(path, changed=False, skipped=True, reason=f"parse error: {e}")

    try:
        validate_header(config)
    except HeaderError as e:
        return FileResult(path, changed=False, skipped=True, reason=str(e))

    new_bytes = render_document(config, xenia_order)

    if new_bytes == original_bytes:
        return FileResult(path, changed=False)

    if check_only:
        logger.info(f"would rewrite: {path}")
        return FileResult(path, changed=True)

    try:
        path.write_bytes(new_bytes)
    except OSError as e:
        return FileResult(path, changed=False, skipped=True, reason=f"write error: {e}")

    logger.info(f"rewrote: {path}")
    return FileResult(path, changed=True)


# =========================
# Main
# =========================


def collect_toml_files(settings_dir: str) -> List[Path]:
    settings_path = Path(settings_dir)
    if not settings_path.exists() or not settings_path.is_dir():
        logger.error(f"Settings directory not found: {settings_path}")
        sys.exit(1)
    files = sorted(settings_path.glob("*.toml"))
    logger.info(f"Found {len(files)} .toml files in {settings_path}")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Format optimized settings .toml files to a consistent style.",
    )
    parser.add_argument(
        "settings_dir",
        nargs="?",
        default=DEFAULT_SETTINGS_DIR,
        help=f"Path to settings directory (default: {DEFAULT_SETTINGS_DIR})",
    )
    parser.add_argument(
        "--xenia-config",
        default=None,
        help="Path to xenia config.toml (used to derive canonical section order). "
        "If omitted, existing section order is preserved as-is.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry run: print files that would change and exit non-zero if any",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    xenia_order: Optional[List[str]] = None
    if args.xenia_config is not None:
        xenia_path = Path(args.xenia_config)
        if not xenia_path.exists():
            logger.error(f"Xenia config file not found: {xenia_path}")
            sys.exit(1)

        try:
            xenia_config = ConfigFile.load(str(xenia_path))
        except Exception as e:
            logger.error(f"Failed to load Xenia config: {e}")
            sys.exit(1)

        xenia_order = canonical_section_order(xenia_config)
        logger.info(
            f"Canonical section order ({len(xenia_order)} sections) loaded from {xenia_path.name}"
        )
    else:
        logger.info("No --xenia-config provided; preserving existing section order")

    toml_files = collect_toml_files(args.settings_dir)
    if not toml_files:
        logger.warning("No .toml files to format")
        sys.exit(0)

    results: List[FileResult] = []
    for path in toml_files:
        result = process_file(path, xenia_order, check_only=args.check)
        results.append(result)
        if result.skipped:
            logger.warning(f"skipped: {path.name} ({result.reason})")

    changed = sum(1 for r in results if r.changed)
    skipped = sum(1 for r in results if r.skipped)
    unchanged = len(results) - changed - skipped

    logger.info("-" * 60)
    logger.info("SUMMARY")
    logger.info("-" * 60)
    logger.info(f"Total files: {len(results)}")
    logger.info(f"Changed: {changed}")
    logger.info(f"Unchanged: {unchanged}")
    logger.info(f"Skipped: {skipped}")

    if args.check and changed > 0:
        logger.info(f"Run without --check to apply {changed} change(s).")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
