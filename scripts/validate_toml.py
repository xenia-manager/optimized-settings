#!/usr/bin/env python3
"""
TOML Validation Script for Xenia Manager Optimized Settings

Validates .toml files in the settings directory to ensure they follow the correct format:
- First 2 lines must contain commented Title Name & Title ID
- All config options must have inline comments
- Values must be of valid types (Boolean, Integer, Float, String, Array)
"""

import argparse
import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import tomllib

# Valid types
VALID_TYPES = {"Boolean", "Integer", "Float", "String", "Array"}

logger = logging.getLogger(__name__)


@dataclass
class ValidationResults:
    """Container for validation results."""

    valid_files: List[str] = field(default_factory=list)
    invalid_files: List[str] = field(default_factory=list)
    header_errors: List[Tuple[str, int, str]] = field(default_factory=list)
    comment_errors: List[Tuple[str, int, str, str]] = field(
        default_factory=list
    )  # (file, line, config, message)
    type_errors: List[Tuple[str, int, str, str, str]] = field(
        default_factory=list
    )  # (file, line, config, expected, actual)
    parse_errors: List[Tuple[str, str]] = field(default_factory=list)  # (file, error)

    def merge(self, other: "ValidationResults") -> None:
        """Merge another ValidationResults into this one."""
        self.valid_files.extend(other.valid_files)
        self.invalid_files.extend(other.invalid_files)
        self.header_errors.extend(other.header_errors)
        self.comment_errors.extend(other.comment_errors)
        self.type_errors.extend(other.type_errors)
        self.parse_errors.extend(other.parse_errors)


def get_value_type(value: Any) -> str:
    """Determine the type of a TOML value."""
    if isinstance(value, bool):
        return "Boolean"
    elif isinstance(value, int):
        return "Integer"
    elif isinstance(value, float):
        return "Float"
    elif isinstance(value, str):
        return "String"
    elif isinstance(value, list):
        return "Array"
    else:
        return "Unknown"


def validate_header(
    lines: List[str], file_path: str
) -> Tuple[bool, List[Tuple[str, int, str]]]:
    """Validate the first 2 lines contain required comments."""
    errors = []

    if len(lines) < 2:
        errors.append(
            (
                file_path,
                1,
                "File must have at least 2 lines for Title Name and Title ID comments",
            )
        )
        return False, errors

    is_valid = True

    # Check first line: # Title Name: <name>
    line1 = lines[0].strip()
    if not line1.startswith("#"):
        errors.append(
            (
                file_path,
                1,
                f"First line must be a comment starting with '#', got: '{line1}'",
            )
        )
        is_valid = False
    elif not re.match(r"^#\s*Title\s+Name\s*:\s*\S", line1, re.IGNORECASE):
        errors.append(
            (
                file_path,
                1,
                f"First line must contain 'Title Name' followed by a value, got: '{line1}'",
            )
        )
        is_valid = False

    # Check second line: # Title ID: <id>
    line2 = lines[1].strip()
    if not line2.startswith("#"):
        errors.append(
            (
                file_path,
                2,
                f"Second line must be a comment starting with '#', got: '{line2}'",
            )
        )
        is_valid = False
    elif not re.match(r"^#\s*Title\s+ID\s*:\s*\S", line2, re.IGNORECASE):
        errors.append(
            (file_path, 2, f"Second line must contain 'Title ID', got: '{line2}'")
        )
        is_valid = False

    return is_valid, errors


def validate_config_comments(
    lines: List[str], file_path: str
) -> List[Tuple[str, int, str, str]]:
    """Validate that all config options have inline comments."""
    errors = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip empty lines and pure comments
        if not stripped or stripped.startswith("#"):
            continue

        # Check for section headers
        if stripped.startswith("[") and stripped.endswith("]"):
            continue

        # Config line - must have inline comment
        if "=" in stripped:
            if "#" not in stripped:
                config_name = stripped.split("=")[0].strip()
                errors.append(
                    (
                        file_path,
                        i,
                        config_name,
                        "Config option must have an inline comment explaining its purpose",
                    )
                )

    return errors


def validate_value_types(
    data: Dict, raw_lines: List[str], file_path: str, section_prefix: str = ""
) -> List[Tuple[str, int, str, str, str]]:
    """Validate that config values are of valid types and belong to sections."""
    errors = []

    for key, value in data.items():
        full_key = f"{section_prefix}.{key}" if section_prefix else key

        if isinstance(value, dict):
            # Nested section - recurse
            errors.extend(validate_value_types(value, raw_lines, file_path, full_key))
        else:
            # Check if config value is at top level (not in any section)
            if not section_prefix:
                line_num = find_config_line(raw_lines, key)
                errors.append(
                    (
                        file_path,
                        line_num,
                        key,
                        "Config value must be inside a section (e.g., [GPU], [APU])",
                        "top-level",
                    )
                )

            actual_type = get_value_type(value)

            if actual_type not in VALID_TYPES:
                line_num = find_config_line(raw_lines, key)
                errors.append(
                    (
                        file_path,
                        line_num,
                        full_key,
                        f"Expected one of: {', '.join(sorted(VALID_TYPES))}",
                        actual_type,
                    )
                )

    return errors


def find_config_line(lines: List[str], config_name: str) -> int:
    """Find the line number of a config option."""
    pattern = re.compile(rf"^\s*{re.escape(config_name)}\s*=")
    for i, line in enumerate(lines, 1):
        if pattern.match(line):
            return i
    return 0


def validate_file(file_path: str) -> ValidationResults:
    """Validate a single TOML file."""
    results = ValidationResults()

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.splitlines()
        file_valid = True

        # Validate header
        header_valid, header_errors = validate_header(lines, file_path)
        results.header_errors.extend(header_errors)
        if not header_valid:
            file_valid = False

        # Validate config comments
        comment_errors = validate_config_comments(lines, file_path)
        results.comment_errors.extend(comment_errors)
        if comment_errors:
            file_valid = False

        # Parse TOML and validate types
        try:
            data = tomllib.loads(content)
            type_errors = validate_value_types(data, lines, file_path)
            results.type_errors.extend(type_errors)
            if type_errors:
                file_valid = False
        except Exception as e:
            results.parse_errors.append((file_path, str(e)))
            file_valid = False

        if file_valid:
            results.valid_files.append(file_path)
        else:
            results.invalid_files.append(file_path)

        return results

    except FileNotFoundError:
        results.parse_errors.append((file_path, "File not found"))
        results.invalid_files.append(file_path)
        return results
    except Exception as e:
        results.parse_errors.append((file_path, f"Unexpected error: {str(e)}"))
        results.invalid_files.append(file_path)
        return results


def validate_directory(directory: str) -> ValidationResults:
    """Validate all TOML files in a directory."""
    results = ValidationResults()

    toml_files = sorted(Path(directory).glob("*.toml"))

    logger.info("Found %d TOML files to validate", len(toml_files))

    for toml_file in toml_files:
        file_results = validate_file(str(toml_file))
        results.merge(file_results)

    return results


def report(results: ValidationResults, total_files: int) -> bool:
    """Print the full report. Returns True if there are errors."""
    div = "=" * 60

    print(f"\n{div}\nSUMMARY\n{div}")
    print(f"Total files validated:                 {total_files}")
    print(f"Valid files:                           {len(results.valid_files)}")
    print(f"Invalid files:                         {len(results.invalid_files)}")
    print(f"Header errors:                         {len(results.header_errors)}")
    print(f"Missing comment errors:                {len(results.comment_errors)}")
    print(f"Type errors:                           {len(results.type_errors)}")
    print(f"Parse errors:                          {len(results.parse_errors)}")

    has_errors = len(results.invalid_files) > 0

    print(
        f"\n{div}\nHEADER ERRORS - missing or malformed Title Name/ID comments\n{div}"
    )
    if results.header_errors:
        for file_path, line_number, error_msg in results.header_errors:
            print(f"  {file_path}:{line_number}")
            print(f"    {error_msg}")
        print(f"\n[WARN] {len(results.header_errors)} header error(s) found")
    else:
        print("\n[OK] All files have valid headers")

    print(f"\n{div}\nMISSING COMMENTS - config options without inline comments\n{div}")
    if results.comment_errors:
        for file_path, line_number, config_name, error_msg in results.comment_errors:
            print(f"  {file_path}:{line_number}")
            print(f"    {config_name} - {error_msg}")
        print(f"\n[WARN] {len(results.comment_errors)} missing comment(s) found")
    else:
        print("\n[OK] All config options have inline comments")

    print(f"\n{div}\nTYPE ERRORS - config values with invalid types\n{div}")
    if results.type_errors:
        for (
            file_path,
            line_number,
            config_name,
            expected,
            actual,
        ) in results.type_errors:
            print(f"  {file_path}:{line_number}")
            if actual == "top-level":
                print(f"    {config_name} - {expected}")
            else:
                print(f"    {config_name} - {actual} (expected: {expected})")
        print(f"\n[WARN] {len(results.type_errors)} type error(s) found")
    else:
        print("\n[OK] All config values have valid types")

    print(f"\n{div}\nPARSE ERRORS - TOML parsing failures\n{div}")
    if results.parse_errors:
        for file_path, error_msg in results.parse_errors:
            print(f"  {file_path}")
            print(f"    {error_msg}")
        print(f"\n[WARN] {len(results.parse_errors)} parse error(s) found")
    else:
        print("\n[OK] All files parsed successfully")

    return has_errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate TOML files for Xenia Manager Optimized Settings"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="settings",
        help="Path to a TOML file or directory containing TOML files (default: settings)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    path = Path(args.path)

    if not path.exists():
        logger.error("Path '%s' does not exist", path)
        sys.exit(1)

    if path.is_file():
        results = validate_file(str(path))
        has_errors = report(results, 1)
    elif path.is_dir():
        results = validate_directory(str(path))
        has_errors = report(results, len(list(path.glob("*.toml"))))
    else:
        logger.error("'%s' is neither a file nor a directory", path)
        sys.exit(1)

    div = "=" * 60
    print(f"\n{div}")
    print(
        "RESULT: FAILED - Validation errors detected"
        if has_errors
        else "RESULT: PASSED - All TOML files are valid"
    )
    print(div)

    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
