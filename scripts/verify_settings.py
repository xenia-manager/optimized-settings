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
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
# Data Model
# =========================


class ConfigOptionType(Enum):
    UNKNOWN = "Unknown"
    BOOLEAN = "Boolean"
    INTEGER = "Integer"
    FLOAT = "Float"
    STRING = "String"
    ARRAY = "Array"


@dataclass
class ConfigOption:
    name: str
    value: Any
    comment: Optional[str] = None
    is_commented: bool = False
    type: ConfigOptionType = ConfigOptionType.UNKNOWN


@dataclass
class ConfigSection:
    name: str
    options: List[ConfigOption] = field(default_factory=list)

    def add_option(
        self,
        name: str,
        value: Any,
        comment: Optional[str] = None,
        is_commented: bool = False,
        type: ConfigOptionType = ConfigOptionType.UNKNOWN,
    ) -> ConfigOption:
        option = ConfigOption(name, value, comment, is_commented, type)
        self.options.append(option)
        return option

    def get_option(self, name: str) -> Optional[ConfigOption]:
        for opt in self.options:
            if opt.name == name:
                return opt
        return None


class ConfigDocument:
    def __init__(self):
        self.sections: List[ConfigSection] = []
        self.header_comment: Optional[str] = None

    def add_section(self, name: str) -> ConfigSection:
        section = ConfigSection(name)
        self.sections.append(section)
        return section

    def get_section(self, name: str) -> Optional[ConfigSection]:
        for s in self.sections:
            if s.name == name:
                return s
        return None


# =========================
# TOML Parser
# =========================


class ConfigFile:
    def __init__(self):
        self.document = ConfigDocument()

    @property
    def sections(self) -> List[ConfigSection]:
        return self.document.sections

    @property
    def header_comment(self) -> Optional[str]:
        return self.document.header_comment

    def get_section(self, name: str) -> Optional[ConfigSection]:
        return self.document.get_section(name)

    @classmethod
    def load(cls, file_path: str) -> "ConfigFile":
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Configuration file does not exist at {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return cls.from_string(content)

    @classmethod
    def from_string(cls, content: str) -> "ConfigFile":
        config = cls()
        config.document = ConfigDocument()
        cls._parse_raw_content(content, config)
        return config

    @staticmethod
    def _parse_raw_content(raw_toml: str, config: "ConfigFile") -> None:
        lines = raw_toml.replace("\r\n", "\n").replace("\r", "\n").split("\n")

        current_section: Optional[ConfigSection] = None
        current_option: Optional[ConfigOption] = None

        for line in lines:
            trimmed = line.strip()

            if (
                trimmed.startswith("#")
                and current_section is None
                and len(config.sections) == 0
            ):
                comment_text = trimmed[1:].strip()
                if config.document.header_comment is None:
                    config.document.header_comment = comment_text
                else:
                    config.document.header_comment += "\n" + comment_text
                continue

            if trimmed.startswith("["):
                match = re.match(r"^\[([^\]]+)\]", trimmed)
                if match:
                    current_section = config.document.add_section(
                        match.group(1).strip()
                    )
                    current_option = None
                continue

            if not trimmed:
                continue

            if (
                current_option is not None
                and line
                and (line.startswith(" ") or line.startswith("\t"))
                and trimmed.startswith("#")
            ):
                comment_text = trimmed[1:].strip()
                if current_option.comment is None:
                    current_option.comment = comment_text
                else:
                    current_option.comment += "\n" + comment_text
                continue

            if current_section is not None and "=" in trimmed:
                current_option = ConfigFile._parse_option_line(trimmed, current_section)

    @staticmethod
    def _parse_option_line(
        trimmed_line: str, section: ConfigSection
    ) -> Optional[ConfigOption]:
        is_commented = trimmed_line.startswith("#")
        line_without_comment = (
            trimmed_line[1:].strip() if is_commented else trimmed_line
        )

        eq_index = line_without_comment.find("=")
        if eq_index == -1:
            return None

        option_name = line_without_comment[:eq_index].strip()
        value_and_comment = line_without_comment[eq_index + 1 :]

        comment_index = -1
        in_quotes = False
        quote_char = "\0"

        for i, c in enumerate(value_and_comment):
            if (c == '"' or c == "'") and (i == 0 or value_and_comment[i - 1] != "\\"):
                if not in_quotes:
                    in_quotes = True
                    quote_char = c
                elif c == quote_char:
                    in_quotes = False
                    quote_char = "\0"

            if not in_quotes and c == "#":
                if i > 0 and (
                    value_and_comment[i - 1].isspace()
                    or value_and_comment[i - 1] == "\t"
                ):
                    comment_index = i
                    break

        if comment_index >= 0:
            value_part = value_and_comment[:comment_index].strip()
            inline_comment = value_and_comment[comment_index + 1 :].strip()
        else:
            value_part = value_and_comment.strip()
            inline_comment = None

        value, opt_type = ConfigFile._parse_value(value_part)
        return section.add_option(
            option_name, value, inline_comment, is_commented, opt_type
        )

    @staticmethod
    def _parse_value(value_str: str) -> Tuple[Any, ConfigOptionType]:
        value_str = value_str.strip()

        if not value_str:
            return "", ConfigOptionType.STRING

        if value_str.lower() == "true":
            return True, ConfigOptionType.BOOLEAN
        if value_str.lower() == "false":
            return False, ConfigOptionType.BOOLEAN

        if (value_str.startswith('"') and value_str.endswith('"')) or (
            value_str.startswith("'") and value_str.endswith("'")
        ):
            return value_str[1:-1], ConfigOptionType.STRING

        if value_str.startswith("[") and value_str.endswith("]"):
            return ConfigFile._parse_array_value(value_str), ConfigOptionType.ARRAY

        try:
            return int(value_str), ConfigOptionType.INTEGER
        except ValueError:
            pass

        try:
            return float(value_str), ConfigOptionType.FLOAT
        except ValueError:
            pass

        return value_str, ConfigOptionType.STRING

    @staticmethod
    def _parse_array_value(array_str: str) -> List[Any]:
        inner = array_str[1:-1].strip()
        if not inner:
            return []

        result = []
        for part in inner.split(","):
            trimmed = part.strip()
            if not trimmed:
                continue

            if trimmed.lower() == "true":
                result.append(True)
            elif trimmed.lower() == "false":
                result.append(False)
            elif (trimmed.startswith('"') and trimmed.endswith('"')) or (
                trimmed.startswith("'") and trimmed.endswith("'")
            ):
                result.append(trimmed[1:-1])
            else:
                try:
                    result.append(int(trimmed))
                except ValueError:
                    try:
                        result.append(float(trimmed))
                    except ValueError:
                        result.append(trimmed)
        return result


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


def format_value(value: Any, opt_type: ConfigOptionType) -> str:
    if value is None:
        return '""'
    if opt_type == ConfigOptionType.BOOLEAN:
        return "true" if value else "false"
    if opt_type == ConfigOptionType.STRING:
        return f'"{value}"'
    if opt_type == ConfigOptionType.ARRAY:
        items = []
        for item in value:
            if isinstance(item, bool):
                items.append("true" if item else "false")
            elif isinstance(item, str):
                items.append(f'"{item}"')
            else:
                items.append(str(item))
        return "[" + ", ".join(items) + "]"
    return str(value)


def extract_title_info(config: ConfigFile) -> Tuple[str, str]:
    title_id = "unknown"
    game_title = "unknown"

    if config.header_comment:
        for line in config.header_comment.split("\n"):
            match_id = re.match(r"Title\s*ID\s*:\s*(\S+)", line, re.IGNORECASE)
            match_name = re.match(r"Title\s*Name\s*:\s*(.+)", line, re.IGNORECASE)
            if match_id:
                title_id = match_id.group(1).strip()
            if match_name:
                game_title = match_name.group(1).strip()

    return title_id, game_title


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

            if xenia_option.type != optimized_option.type:
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
            elif xenia_option.value == optimized_option.value:
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
