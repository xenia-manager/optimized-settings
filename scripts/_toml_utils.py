"""
Shared TOML parsing and formatting utilities used by the verify and format
scripts. Centralises the comment-preserving ConfigFile parser so both scripts
agree on the document model.
"""

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Tuple

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
# Helpers
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
    if opt_type == ConfigOptionType.FLOAT:
        if isinstance(value, float):
            return repr(value) if not value.is_integer() else f"{value:.1f}"
        return str(value)
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
