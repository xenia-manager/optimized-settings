#!/usr/bin/env python3
"""
Compare Optimized Settings Against Xenia Config

Checks .toml files in the settings folder against a Xenia config.toml file
and reports any missing or mismatched settings.

- Uses custom comment-preserving TOML parser
- Supports checking individual files or entire directories
"""

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _toml_utils import (
    ConfigFile,
    ConfigOptionType,
    extract_title_info,
    format_value,
)

# =========================
# Logging Configuration
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# =========================
# Configuration
# =========================
DEFAULT_SETTINGS_DIR = "settings"

# =========================
# Issue Model
# =========================


@dataclass
class SettingIssue:
    title_id: str
    game_title: str
    section_name: str
    option_name: str
    expected_value: Any
    expected_type: ConfigOptionType
    current_value: Optional[Any] = None
    comment: Optional[str] = None
    issue_type: str = "missing"

    @property
    def current_value_type(self) -> str:
        if self.current_value is None:
            return "None"
        if isinstance(self.current_value, bool):
            return "Boolean"
        if isinstance(self.current_value, int):
            return "Integer"
        if isinstance(self.current_value, float):
            return "Float"
        if isinstance(self.current_value, str):
            return "String"
        if isinstance(self.current_value, (list, tuple)):
            return "Array"
        return "Unknown"


# =========================
# Helper Functions
# =========================


def get_value_type_name(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, int):
        return "Integer"
    if isinstance(value, float):
        return "Float"
    if isinstance(value, str):
        return "String"
    if isinstance(value, (list, tuple)):
        return "Array"
    return "Unknown"


def types_compatible(a: ConfigOptionType, b: ConfigOptionType) -> bool:
    if a == b:
        return True
    return {a, b} == {ConfigOptionType.INTEGER, ConfigOptionType.FLOAT}


def values_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, float) or isinstance(b, float):
        try:
            return float(a) == float(b)
        except (TypeError, ValueError):
            return False
    return a == b


# =========================
# Comparison Logic
# =========================


def compare_configs(
    xenia_config: ConfigFile,
    optimized_config: ConfigFile,
    title_id: str,
    game_title: str,
) -> List[SettingIssue]:
    issues = []

    xenia_section_order = {s.name: i for i, s in enumerate(xenia_config.sections)}

    last_xenia_index = -1
    has_order_issue = False
    for optimized_section in optimized_config.sections:
        for optimized_option in optimized_section.options:
            if optimized_option.is_commented:
                continue

            if optimized_section.name not in xenia_section_order:
                logger.debug(f"Missing section: [{optimized_section.name}]")
                issues.append(
                    SettingIssue(
                        title_id=title_id,
                        game_title=game_title,
                        section_name=optimized_section.name,
                        option_name=optimized_option.name,
                        expected_value=optimized_option.value,
                        expected_type=optimized_option.type,
                        comment=optimized_option.comment,
                        issue_type="missing_section",
                    )
                )
                continue

            xenia_section = xenia_config.get_section(optimized_section.name)
            xenia_option = xenia_section.get_option(optimized_option.name)

            if xenia_option is None:
                logger.debug(
                    f"Missing option: [{optimized_section.name}] {optimized_option.name}"
                )
                issues.append(
                    SettingIssue(
                        title_id=title_id,
                        game_title=game_title,
                        section_name=optimized_section.name,
                        option_name=optimized_option.name,
                        expected_value=optimized_option.value,
                        expected_type=optimized_option.type,
                        comment=optimized_option.comment,
                        issue_type="missing_option",
                    )
                )
                continue

            if not types_compatible(xenia_option.type, optimized_option.type):
                logger.debug(
                    f"Type mismatch: [{optimized_section.name}] {optimized_option.name} "
                    f"(expected {optimized_option.type.value}, got {get_value_type_name(xenia_option.value)})"
                )
                issues.append(
                    SettingIssue(
                        title_id=title_id,
                        game_title=game_title,
                        section_name=optimized_section.name,
                        option_name=optimized_option.name,
                        expected_value=optimized_option.value,
                        expected_type=optimized_option.type,
                        current_value=xenia_option.value,
                        comment=optimized_option.comment,
                        issue_type="type_mismatch",
                    )
                )
            elif values_equal(xenia_option.value, optimized_option.value):
                logger.debug(
                    f"Value match: [{optimized_section.name}] {optimized_option.name} "
                    f"(already using default value: {optimized_option.value})"
                )
                issues.append(
                    SettingIssue(
                        title_id=title_id,
                        game_title=game_title,
                        section_name=optimized_section.name,
                        option_name=optimized_option.name,
                        expected_value=optimized_option.value,
                        expected_type=optimized_option.type,
                        current_value=xenia_option.value,
                        comment=optimized_option.comment,
                        issue_type="value_match",
                    )
                )

        section_xenia_index = xenia_section_order.get(optimized_section.name, -1)
        if section_xenia_index >= 0 and section_xenia_index < last_xenia_index:
            if not has_order_issue:
                logger.debug("Section order mismatch detected")
                issues.append(
                    SettingIssue(
                        title_id=title_id,
                        game_title=game_title,
                        section_name="",
                        option_name="",
                        expected_value=0,
                        expected_type=ConfigOptionType.UNKNOWN,
                        current_value=0,
                        issue_type="section_order",
                    )
                )
                has_order_issue = True
        elif section_xenia_index >= 0:
            last_xenia_index = section_xenia_index

    return issues


# =========================
# Output Functions
# =========================


def print_file_issues(
    issues: List[SettingIssue],
    optimized_config: Optional[ConfigFile] = None,
    xenia_config: Optional[ConfigFile] = None,
) -> None:
    if not issues:
        return

    logger.warning(f"{len(issues)} issue(s) found:")

    for issue in issues:
        if issue.issue_type == "section_order":
            actual_order = (
                [s.name for s in optimized_config.sections] if optimized_config else []
            )
            correct_order = (
                [s.name for s in xenia_config.sections] if xenia_config else []
            )
            logger.error(
                f"Wrong section order - {actual_order}, correct order - {correct_order}"
            )
        elif issue.issue_type == "type_mismatch":
            logger.error(
                f"[{issue.section_name}] {issue.option_name} = {format_value(issue.expected_value, issue.expected_type)} (type mismatch - expected {issue.expected_type.value}, got {issue.current_value_type})"
            )
        elif issue.issue_type == "value_match":
            logger.warning(
                f"[{issue.section_name}] {issue.option_name} = {format_value(issue.expected_value, issue.expected_type)} (already using default value)"
            )
        elif issue.issue_type == "missing_section":
            logger.error(
                f"[{issue.section_name}] {issue.option_name} = {format_value(issue.expected_value, issue.expected_type)} (section missing)"
            )
        else:
            logger.error(
                f"[{issue.section_name}] {issue.option_name} = {format_value(issue.expected_value, issue.expected_type)} (missing)"
            )


# =========================
# File Collection
# =========================


def collect_toml_files(settings_dir: Optional[str], files: List[str]) -> List[Path]:
    toml_files: List[Path] = []

    if files:
        for f in files:
            p = Path(f)
            if not p.exists():
                logger.warning(f"File not found, skipping: {p}")
            elif not p.is_file():
                logger.warning(f"Not a file, skipping: {p}")
            else:
                toml_files.append(p)

    if settings_dir is not None:
        settings_path = Path(settings_dir)
        if not settings_path.exists() or not settings_path.is_dir():
            logger.error(f"Settings directory not found: {settings_path}")
            sys.exit(1)
        dir_files = sorted(settings_path.glob("*.toml"))
        toml_files.extend(dir_files)
        logger.info(f"Found {len(dir_files)} .toml files in {settings_dir}")
    elif not files:
        settings_path = Path(DEFAULT_SETTINGS_DIR)
        if settings_path.exists() and settings_path.is_dir():
            dir_files = sorted(settings_path.glob("*.toml"))
            toml_files.extend(dir_files)
            logger.info(f"Found {len(dir_files)} .toml files in {DEFAULT_SETTINGS_DIR}")
        else:
            logger.warning(
                f"Default settings directory not found: {DEFAULT_SETTINGS_DIR}"
            )

    seen = set()
    unique_files = []
    for f in toml_files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(f)

    logger.info(f"Total unique files to check: {len(unique_files)}")
    return unique_files


# =========================
# Main Function
# =========================


def main() -> None:
    start_time = time.time()

    parser = argparse.ArgumentParser(
        description="Compare optimized settings against Xenia config.toml"
    )
    parser.add_argument(
        "xenia_config",
        help="Path to Xenia config.toml file",
    )
    parser.add_argument(
        "--settings-dir",
        default=None,
        help="Path to settings directory containing .toml files (default: settings if no --files specified)",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        default=[],
        help="Individual .toml files to check (can be combined with --settings-dir)",
    )

    args = parser.parse_args()

    xenia_path = Path(args.xenia_config)

    logger.info("=" * 60)
    logger.info("Xenia Manager - Optimized Settings Comparison")
    logger.info("=" * 60)
    logger.info(f"Xenia config: {xenia_path}")

    if not xenia_path.exists():
        logger.error(f"Xenia config file not found: {xenia_path}")
        sys.exit(1)

    toml_files = collect_toml_files(args.settings_dir, args.files)

    if not toml_files:
        logger.warning("No .toml files to check")
        sys.exit(0)

    try:
        xenia_config = ConfigFile.load(str(xenia_path))
        logger.info(f"Loaded Xenia config with {len(xenia_config.sections)} sections")
    except Exception as e:
        logger.error(f"Failed to load Xenia config: {e}")
        sys.exit(1)

    all_issues: List[SettingIssue] = []
    files_processed = 0
    files_skipped = 0
    files_with_issues = 0
    issue_types: Dict[str, int] = {}

    logger.info("-" * 60)

    for toml_file in toml_files:
        try:
            optimized_config = ConfigFile.load(str(toml_file))
            title_id, game_title = extract_title_info(optimized_config)

            logger.info(f"Checking {game_title} ({title_id})...")

            issues = compare_configs(
                xenia_config, optimized_config, title_id, game_title
            )
            all_issues.extend(issues)
            files_processed += 1

            if issues:
                files_with_issues += 1
                print_file_issues(issues, optimized_config, xenia_config)

            for issue in issues:
                issue_types[issue.issue_type] = issue_types.get(issue.issue_type, 0) + 1

        except Exception as e:
            logger.warning(f"Failed to process {toml_file.name}: {e}")
            files_skipped += 1

    if not all_issues:
        logger.info("All optimized settings checked. No issues found.")
    elif all(i.issue_type == "value_match" for i in all_issues):
        logger.info("All issues are value matches (already using defaults).")

    elapsed_time = time.time() - start_time

    logger.info("-" * 60)
    logger.info("SUMMARY")
    logger.info("-" * 60)
    logger.info(f"Total files checked: {len(toml_files)}")
    logger.info(f"Files processed successfully: {files_processed}")
    logger.info(f"Files with issues: {files_with_issues}")
    logger.info(f"Files skipped (errors): {files_skipped}")
    logger.info(f"Total issues found: {len(all_issues)}")

    if issue_types:
        logger.info(f"Issue breakdown: {issue_types}")

    logger.info(f"Execution time: {elapsed_time:.2f}s")
    logger.info("=" * 60)

    has_errors = any(i.issue_type != "value_match" for i in all_issues)
    sys.exit(1 if has_errors else 0)


# Entry point
if __name__ == "__main__":
    main()
