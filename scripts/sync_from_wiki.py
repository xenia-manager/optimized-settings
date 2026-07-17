#!/usr/bin/env python3
"""
Compare AleNaz's Xenia Game Settings Wiki against the optimized-settings repo
and report differences: new games, missing settings, and unmatched pages.

Usage:
    python scripts/sync_from_wiki.py --wiki-dir "path/to/AleNaz's Settings Wiki"

Output:
    Writes a Markdown report to scripts/sync_report.md (or --output <path>).
    Writes TOML files sorted into category folders with --output-files <dir>.
    Does NOT modify any files under settings/.
"""

import argparse
import json
import logging
import os
import re
import string
import subprocess
import sys
import unicodedata
from collections import OrderedDict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.request import urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _toml_utils import ConfigFile, ConfigOptionType, format_value

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

X360DB_URL = "https://raw.githubusercontent.com/xenia-manager/x360db/refs/heads/main/games.json"
SETTINGS_DIR = (Path(__file__).parent.parent / "settings").resolve()
REPORT_DEFAULT = (Path(__file__).parent / "sync_report.md").resolve()

CAT_NEW = "new_games"
CAT_MISSING = "missing_settings"
CAT_DIFF = "value_diffs"
CAT_UNMATCHED = "unmatched"

KEY_TO_SECTION: Dict[str, str] = {
    "vsync": "GPU",
    "framerate_limit": "GPU",
    "occlusion_query": "GPU",
    "render_target_path_d3d12": "D3D12",
    "readback_memexport": "GPU",
    "depth_float24_convert_in_pixel_shader": "GPU",
    "query_occlusion_querybatch_range": "GPU",
    "readback_resolve": "GPU",
    "clear_memory_page_state": "GPU",
    "gpu_allow_invalid_fetch_constants": "GPU",
    "disable_context_promotion": "GPU",
    "mount_cache": "GPU",
    "use_dedicated_xma_thread": "CPU",
    "xma_decoder": "CPU",
    "controller_hotkeys": "General",
    "protect_disassemble": "GPU",
    "audio": "General",
    "cl": "Config",
    "gpu": "GPU",
    "internal_display_resolution": "GPU",
}

DEFAULT_SECTION = "GPU"
SKIP_WIKI_FILES = {"home.md", "_sidebar.md", "_footer.md"}

SECTION_ORDER = [
    "APU", "CPU", "Config", "Content", "D3D12", "Display", "GPU",
    "General", "HACKS", "HID", "HID.WinKey", "Kernel", "Live",
    "Logging", "Memory", "MouseHook", "Profiles", "SDL", "Storage",
    "UI", "Video", "Vulkan", "Win32", "XConfig", "x64",
]


def sanitize_filename(name: str, max_len: int = 60) -> str:
    t = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[':&/\\]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace(" ", "-")
    t = re.sub(r"[^A-Za-z0-9-]", "", t)
    t = t.strip("-")
    return t[:max_len] or "unknown"


def normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[':&]", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fetch_x360db(url: str = X360DB_URL) -> List[Dict[str, Any]]:
    logger.info(f"Fetching x360db from {url}")
    try:
        resp = urlopen(url, timeout=30)
        data = json.loads(resp.read().decode("utf-8"))
        logger.info(f"Loaded {len(data)} games from x360db")
        return data
    except Exception as e:
        logger.warning(f"Failed to fetch x360db: {e}")
        return []


def build_x360db_index(db: List[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, str]]:
    title_to_id: Dict[str, str] = {}
    id_to_title: Dict[str, str] = {}
    for entry in db:
        tid = entry.get("id", "")
        title = entry.get("title", "").strip()
        if tid and title:
            id_to_title[tid] = title
            norm = normalize_title(title)
            title_to_id[norm] = tid
    return title_to_id, id_to_title


def build_fuzzy_index(title_to_id: Dict[str, str]) -> Tuple[List[str], List[str]]:
    norms = list(title_to_id.keys())
    ids = [title_to_id[n] for n in norms]
    return norms, ids


def fuzzy_find_id(stem: str, norms: List[str], ids: List[str]) -> Optional[str]:
    from difflib import get_close_matches
    wiki_norm = normalize_title(stem.replace("-", " "))
    matches = get_close_matches(wiki_norm, norms, n=1, cutoff=0.6)
    if matches:
        idx = norms.index(matches[0])
        return ids[idx]
    return None


def get_wiki_last_updated(wiki_dir: Path, file_path: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ad", "--date=short", "--", str(file_path)],
            capture_output=True, text=True, cwd=str(wiki_dir), timeout=10,
        )
        date_str = result.stdout.strip()
        return date_str if date_str else None
    except Exception:
        return None


def extract_title_id_from_patch_links(text: str) -> Optional[str]:
    pattern = r"patches/([0-9A-Fa-f]{8})(?:%20|-)"
    matches = re.findall(pattern, text)
    if matches:
        return matches[0].upper()
    return None


def extract_title_id_from_raw_urls(text: str) -> Optional[str]:
    pattern = r"patches/([0-9A-Fa-f]{8})\s*-"
    matches = re.findall(pattern, text)
    if matches:
        return matches[0].upper()
    return None


def extract_title_id(text: str) -> Optional[str]:
    tid = extract_title_id_from_patch_links(text)
    if tid:
        return tid
    return extract_title_id_from_raw_urls(text)


def parse_wiki_settings(content: str) -> List[Tuple[str, str, Optional[str]]]:
    settings: List[Tuple[str, str, Optional[str]]] = []
    in_recommended = False
    lines = content.replace("\r\n", "\n").split("\n")

    for line in lines:
        stripped = line.strip()

        if "Recommended Settings" in stripped:
            in_recommended = True
            continue

        if not in_recommended:
            continue

        if not stripped or stripped.startswith("---"):
            if not stripped:
                continue
            break

        if stripped.startswith("## ") and "Recommended" not in stripped:
            break

        if stripped.startswith("(") and stripped.endswith(")") and settings:
            prev_key, prev_val, _ = settings[-1]
            settings[-1] = (prev_key, prev_val, stripped[1:-1].strip())
            continue

        if "=" in stripped and not stripped.startswith("##"):
            eq_idx = stripped.index("=")
            key = stripped[:eq_idx].strip()
            rest = stripped[eq_idx + 1:].strip()

            in_quotes = False
            quote_char = None
            comment_idx = -1
            for j, c in enumerate(rest):
                if c in ("'", '"') and (j == 0 or rest[j - 1] != "\\"):
                    if not in_quotes:
                        in_quotes = True
                        quote_char = c
                    elif c == quote_char:
                        in_quotes = False
                if not in_quotes and c == "#":
                    comment_idx = j
                    break

            if comment_idx >= 0:
                val_part = rest[:comment_idx].strip()
                comment = rest[comment_idx + 1:].strip()
                html_idx = comment.find("<")
                if html_idx >= 0:
                    comment = comment[:html_idx].strip()
            else:
                val_part = rest
                comment = None

            val_part = val_part.rstrip(",")
            if val_part:
                settings.append((key, val_part, comment))

    return settings


def normalize_setting_value(val: str) -> str:
    v = val.strip().strip(",")
    v = v.strip('"').strip("'")
    return v


def setting_to_section(key: str) -> str:
    return _active_key_to_section.get(key, DEFAULT_SECTION)


_active_key_to_section: Dict[str, str] = dict(KEY_TO_SECTION)


def load_xenia_config_sections(config_path: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    try:
        config = ConfigFile.load(str(config_path))
        for section in config.sections:
            for opt in section.options:
                mapping[opt.name] = section.name
    except Exception as e:
        logger.warning(f"Failed to parse xenia config {config_path}: {e}")
    return mapping


def render_value_literal(val_str: str) -> str:
    v = val_str.strip().strip(",").strip()
    if v.lower() in ("true", "false"):
        return v.lower()
    try:
        int(v)
        return v
    except ValueError:
        pass
    try:
        float(v)
        return v
    except ValueError:
        pass
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v
    return f'"{v}"'


def build_toml_settings_map(config: ConfigFile) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for section in config.sections:
        for opt in section.options:
            if not opt.is_commented:
                result[opt.name] = format_value(opt.value, opt.type)
    return result


def load_existing_settings() -> Dict[str, ConfigFile]:
    result: Dict[str, ConfigFile] = {}
    if not SETTINGS_DIR.exists():
        return result
    for toml_file in sorted(SETTINGS_DIR.glob("*.toml")):
        tid = toml_file.stem.upper()
        try:
            result[tid] = ConfigFile.load(str(toml_file))
        except Exception as e:
            logger.warning(f"Failed to parse {toml_file.name}: {e}")
    logger.info(f"Loaded {len(result)} existing TOML files")
    return result


def extract_title_info_simple(config: ConfigFile) -> Tuple[str, str]:
    title_id = "unknown"
    game_title = "unknown"
    if config.header_comment:
        for line in config.header_comment.split("\n"):
            m_id = re.match(r"Title\s*ID\s*:\s*(\S+)", line, re.IGNORECASE)
            m_name = re.match(r"Title\s*Name\s*:\s*(.+)", line, re.IGNORECASE)
            if m_id:
                title_id = m_id.group(1).strip()
            if m_name:
                game_title = m_name.group(1).strip()
    return title_id, game_title


def get_existing_title(config: ConfigFile) -> str:
    _, title = extract_title_info_simple(config)
    return title


def get_wiki_title_name(filename_stem: str, content: str) -> str:
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## [") and "](" in stripped:
            m = re.match(r"## \[([^\]]+)\]", stripped)
            if m:
                return m.group(1).strip()
    title = filename_stem.replace("-", " ")
    return re.sub(r"\s+", " ", title).strip()


def get_x360_title(title_id: str, id_to_title: Dict[str, str]) -> Optional[str]:
    return id_to_title.get(title_id)


# ── TOML output helpers ──────────────────────────────────────────────────────


def compose_toml_body(settings: List[Tuple[str, str, Optional[str]]]) -> OrderedDict:
    sections: OrderedDict[str, list] = OrderedDict()
    for key, val, comment in settings:
        section = setting_to_section(key)
        if section not in sections:
            sections[section] = []
        sections[section].append((key, val, comment))
    return sections


def render_toml(title_name: str, title_id: str, body: OrderedDict, last_updated: Optional[str] = None) -> str:
    lines = [f"# Title Name: {title_name}", f"# Title ID: {title_id}"]
    if last_updated:
        lines.append(f"# Last Updated: {last_updated}")
    first = True
    for sec in SECTION_ORDER:
        items = body.get(sec, [])
        if not items:
            continue
        if first:
            first = False
        else:
            lines.append("")
        lines.append(f"[{sec}]")
        for key, val, comment in items:
            val_lit = render_value_literal(val)
            line = f"{key} = {val_lit}"
            if comment:
                line += f" # {comment}"
            lines.append(line)
    lines.append("")
    return "\r\n".join(lines)


def render_toml_with_missing(title_name: str, title_id: str, config: ConfigFile, missing: list, last_updated: Optional[str] = None) -> str:
    body = OrderedDict()
    existing_section_items: Dict[str, list] = {}
    for section in config.sections:
        existing_section_items[section.name] = []
        for opt in section.options:
            comment = opt.comment or ""
            existing_section_items[section.name].append((opt.name, format_value(opt.value, opt.type), comment))

    for section in SECTION_ORDER:
        if section in existing_section_items:
            body[section] = existing_section_items[section]

    for item in missing:
        sec = item["section"]
        if sec not in body:
            body[sec] = []
        body[sec].append((item["key"], item["wiki_value"], item["comment"] or ""))

    return render_toml(title_name, title_id, body, last_updated)


def render_toml_different(title_name: str, title_id: str, config: ConfigFile, diffs: list, last_updated: Optional[str] = None) -> str:
    diff_map = {d["key"]: d for d in diffs}
    body = OrderedDict()
    for section in config.sections:
        if section.name not in body:
            body[section.name] = []
        for opt in section.options:
            comment = (opt.comment or "").strip()
            display_val = format_value(opt.value, opt.type)
            if opt.name in diff_map:
                d = diff_map[opt.name]
                wiki_lit = render_value_literal(normalize_setting_value(d["wiki_value"]))
                combined = f"WIKI: {wiki_lit}"
                if comment:
                    combined += f" | {comment}"
                body[section.name].append((opt.name, wiki_lit, combined))
            else:
                body[section.name].append((opt.name, display_val, comment))

    for d in diffs:
        if d["key"] not in {opt[0] for sec in body.values() for opt in sec}:
            body.setdefault(d["section"], []).append((d["key"], render_value_literal(normalize_setting_value(d["wiki_value"])), f"WIKI: {render_value_literal(normalize_setting_value(d['wiki_value']))}"))

    return render_toml(title_name, title_id, body, last_updated)


def write_toml_file(out_dir: Path, filename: str, content: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / filename
    file_path.write_text(content, encoding="utf-8")
    logger.info(f"  Wrote: {file_path.name}")
    return file_path


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync AleNaz's wiki against optimized settings")
    parser.add_argument("--wiki-dir", required=True, help="Path to local clone of AleNaz's Settings Wiki")
    parser.add_argument("--output", default=str(REPORT_DEFAULT), help="Output report path")
    parser.add_argument("--output-files", default=None, help="Output TOML files into category folders")
    parser.add_argument("--no-fetch", action="store_true", help="Skip fetching x360db; use cached games.json")
    parser.add_argument("--cache", action="store_true", help="Save fetched x360db to local cache")
    parser.add_argument("--before-date", nargs="?", const="__last_commit__", default=None, help="Only process wiki files updated from this date (YYYY-MM-DD) until today. Without a value, uses the last git commit date")
    parser.add_argument("--xenia-config", default=None, help="Path to xenia.config.toml to derive section mappings instead of hardcoded KEY_TO_SECTION")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    before_date = None
    if args.before_date:
        if args.before_date == "__last_commit__":
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ad", "--date=short"],
                capture_output=True, text=True, cwd=str(Path(__file__).parent.parent), timeout=10,
            )
            date_str = result.stdout.strip()
            if date_str:
                try:
                    before_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    logger.error(f"Could not parse last commit date: {date_str}")
                    sys.exit(1)
            else:
                logger.error("No git commits found in wiki directory")
                sys.exit(1)
        else:
            try:
                before_date = datetime.strptime(args.before_date, "%Y-%m-%d").date()
            except ValueError:
                logger.error(f"Invalid date format: {args.before_date}. Expected YYYY-MM-DD")
                sys.exit(1)

    today = date.today()

    wiki_path = Path(args.wiki_dir).resolve()
    if not wiki_path.exists() or not wiki_path.is_dir():
        logger.error(f"Wiki directory not found: {wiki_path}")
        sys.exit(1)

    output_path = Path(args.output).resolve()

    global _active_key_to_section
    if args.xenia_config:
        xenia_config_path = Path(args.xenia_config).resolve()
        if not xenia_config_path.exists():
            logger.error(f"Xenia config not found: {xenia_config_path}")
            sys.exit(1)
        xenia_map = load_xenia_config_sections(xenia_config_path)
        if xenia_map:
            _active_key_to_section = xenia_map
            logger.info(f"Loaded {len(xenia_map)} section mappings from {xenia_config_path.name}")

    # ── Load data ──────────────────────────────────────────────────────────────
    x360db_data: List[Dict[str, Any]] = []
    if not args.no_fetch:
        x360db_data = fetch_x360db()
    else:
        cache_path = Path(args.output).parent / "games.json"
        if cache_path.exists():
            with open(str(cache_path), encoding="utf-8") as f:
                x360db_data = json.load(f)
            logger.info(f"Loaded {len(x360db_data)} games from cached {cache_path}")
        else:
            x360db_data = fetch_x360db()

    title_to_id_x360, id_to_title_x360 = build_x360db_index(x360db_data)
    fuzzy_norms, fuzzy_ids = build_fuzzy_index(title_to_id_x360)

    if args.cache and x360db_data:
        cache_path = Path(args.output).parent / "games.json"
        with open(str(cache_path), "w", encoding="utf-8") as f:
            json.dump(x360db_data, f)
        logger.info(f"Cached x360db to {cache_path}")

    existing_settings = load_existing_settings()

    # ── Scan wiki ──────────────────────────────────────────────────────────────
    wiki_files = sorted(wiki_path.glob("*.md"))
    wiki_entries = [wf for wf in wiki_files if wf.stem.lower() not in SKIP_WIKI_FILES]
    logger.info(f"Scanning {len(wiki_entries)} wiki pages...")

    new_games: List[Dict] = []
    missing_settings: List[Dict] = []
    different_settings: List[Dict] = []
    unmatched: List[Dict] = []
    matched_games: List[Dict] = []

    for idx, wf in enumerate(wiki_entries):
        if idx > 0 and idx % 100 == 0:
            logger.info(f"  Progress: {idx}/{len(wiki_entries)}")
        content = wf.read_text(encoding="utf-8", errors="replace")
        last_updated = get_wiki_last_updated(wiki_path, wf)

        if before_date and last_updated:
            try:
                file_date = datetime.strptime(last_updated, "%Y-%m-%d").date()
                if file_date < before_date or file_date > today:
                    continue
            except ValueError:
                pass

        wiki_title = get_wiki_title_name(wf.stem, content)
        settings = parse_wiki_settings(content)

        title_id = extract_title_id(content)

        if not title_id and x360db_data:
            stem_clean = wf.stem.replace("\u2010", "-").replace("\u2019", "'")
            title_id = fuzzy_find_id(stem_clean, fuzzy_norms, fuzzy_ids)

        x360_title = get_x360_title(title_id, id_to_title_x360) if title_id else None

        if not title_id:
            unmatched.append({
                "wiki_file": wf.name,
                "wiki_title": wiki_title,
                "settings": settings,
                "last_updated": last_updated,
            })
            continue

        toml_path = SETTINGS_DIR / f"{title_id}.toml"
        if not toml_path.exists():
            new_games.append({
                "title_id": title_id,
                "wiki_file": wf.name,
                "wiki_title": wiki_title,
                "x360db_title": x360_title,
                "settings": settings,
                "last_updated": last_updated,
            })
            continue

        matched_games.append({
            "title_id": title_id,
            "wiki_file": wf.name,
            "wiki_title": wiki_title,
            "x360db_title": x360_title,
        })

        config = existing_settings.get(title_id)
        if config is None:
            continue

        existing_map = build_toml_settings_map(config)
        existing_keys = set(existing_map.keys())

        file_missing = []
        file_different = []

        for key, val, comment in settings:
            norm_val = normalize_setting_value(val)
            rendered_wiki = render_value_literal(norm_val)

            if key not in existing_keys:
                section = setting_to_section(key)
                file_missing.append({
                    "title_id": title_id,
                    "wiki_title": wiki_title,
                    "key": key,
                    "wiki_value": rendered_wiki,
                    "section": section,
                    "comment": comment or "",
                })
            else:
                existing_val = existing_map[key]
                existing_clean = existing_val.strip().lower().strip('"').strip("'")
                wiki_clean = norm_val.strip().lower().strip('"').strip("'")
                if existing_clean != wiki_clean:
                    file_different.append({
                        "title_id": title_id,
                        "wiki_title": wiki_title,
                        "key": key,
                        "wiki_value": rendered_wiki,
                        "existing_value": existing_val,
                        "section": setting_to_section(key),
                        "comment": comment or "",
                    })

        if file_missing:
            missing_settings.append({
                "title_id": title_id,
                "wiki_file": wf.name,
                "wiki_title": wiki_title,
                "settings": file_missing,
                "config": config,
                "last_updated": last_updated,
            })

        if file_different:
            different_settings.append({
                "title_id": title_id,
                "wiki_file": wf.name,
                "wiki_title": wiki_title,
                "diffs": file_different,
                "config": config,
                "last_updated": last_updated,
            })

    # ── Write category TOML files ──────────────────────────────────────────────
    if args.output_files:
        out_root = Path(args.output_files).resolve()
        logger.info(f"Writing TOML files to {out_root}")

        for ng in new_games:
            title_name = ng.get("x360db_title") or ng["wiki_title"]
            body = compose_toml_body(ng["settings"])
            content = render_toml(title_name, ng["title_id"], body, ng["last_updated"])
            write_toml_file(out_root / CAT_NEW, f"{ng['title_id']}.toml", content)

        for item in missing_settings:
            title_name = item.get("x360db_title") or item["wiki_title"] or item["title_id"]
            content = render_toml_with_missing(title_name, item["title_id"], item["config"], item["settings"], item["last_updated"])
            write_toml_file(out_root / CAT_MISSING, f"{item['title_id']}.toml", content)

        for item in different_settings:
            title_name = item.get("x360db_title") or item["wiki_title"] or item["title_id"]
            content = render_toml_different(title_name, item["title_id"], item["config"], item["diffs"], item["last_updated"])
            write_toml_file(out_root / CAT_DIFF, f"{item['title_id']}.toml", content)

        for item in unmatched:
            name = sanitize_filename(item["wiki_file"].replace(".md", ""))
            body = compose_toml_body(item["settings"])
            content = render_toml(f"UNMATCHED: {item['wiki_title']}", "unknown", body, item["last_updated"])
            write_toml_file(out_root / CAT_UNMATCHED, f"{name}.toml", content)

    # ── Write report ───────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report_lines: List[str] = []
    report_lines.append(f"# Sync Report — {now}")
    report_lines.append("")
    report_lines.append("> Generated by `scripts/sync_from_wiki.py`")
    report_lines.append("")

    total_wiki = len(wiki_entries)
    total_toml = len(existing_settings)
    total_new = len(new_games)
    total_missing = len(missing_settings)
    total_different = len(different_settings)
    total_unmatched = len(unmatched)

    report_lines.append("## Summary")
    report_lines.append("")
    report_lines.append(f"| Metric | Count |")
    report_lines.append(f"|---|---|")
    report_lines.append(f"| Wiki pages scanned | {total_wiki} |")
    report_lines.append(f"| Existing TOML files | {total_toml} |")
    report_lines.append(f"| Matched (TOML exists) | {len(matched_games)} |")
    report_lines.append(f"| **New games found** | **{total_new}** |")
    report_lines.append(f"| **Missing settings** | **{total_missing}** |")
    report_lines.append(f"| **Different values** | **{total_different}** |")
    report_lines.append(f"| Unmatched pages | {total_unmatched} |")
    report_lines.append("")

    if args.output_files:
        report_lines.append(f"| **TOML output directory** | `{Path(args.output_files).resolve()}` |")
        report_lines.append("")
        report_lines.append("Category folders:")
        report_lines.append(f"- `{CAT_NEW}/`")
        report_lines.append(f"- `{CAT_MISSING}/`")
        report_lines.append(f"- `{CAT_DIFF}/`")
        report_lines.append(f"- `{CAT_UNMATCHED}/`")
        report_lines.append("")

    if new_games:
        report_lines.append("---")
        report_lines.append("")
        report_lines.append(f"## New Games ({total_new})")
        report_lines.append("")
        report_lines.append("| Title ID | Wiki Title | x360db Title | Settings Count |")
        report_lines.append("|---|---|---|---|")
        for ng in sorted(new_games, key=lambda x: x["title_id"]):
            x360_d = ng.get("x360db_title") or ""
            report_lines.append(f"| {ng['title_id']} | {ng['wiki_title']} | {x360_d} | {len(ng['settings'])} |")
        report_lines.append("")

    if missing_settings:
        total_ind = sum(len(item["settings"]) for item in missing_settings)
        report_lines.append("---")
        report_lines.append("")
        report_lines.append(f"## Missing Settings ({total_missing} files, {total_ind} entries)")
        report_lines.append("")
        report_lines.append("| Title ID | Title | Key | Value | Section | Comment |")
        report_lines.append("|---|---|---|---|---|---|")
        for item in sorted(missing_settings, key=lambda x: x["title_id"]):
            for s in item["settings"]:
                report_lines.append(f"| {s['title_id']} | {s['wiki_title']} | `{s['key']}` | `{s['wiki_value']}` | `[{s['section']}]` | {s['comment']} |")
        report_lines.append("")

    if different_settings:
        total_ind = sum(len(item["diffs"]) for item in different_settings)
        report_lines.append("---")
        report_lines.append("")
        report_lines.append(f"## Different Values ({total_different} files, {total_ind} entries)")
        report_lines.append("")
        report_lines.append("| Title ID | Title | Key | Wiki Value | Current Value |")
        report_lines.append("|---|---|---|---|---|")
        for item in sorted(different_settings, key=lambda x: x["title_id"]):
            for s in item["diffs"]:
                report_lines.append(f"| {s['title_id']} | {s['wiki_title']} | `{s['key']}` | `{s['wiki_value']}` | `{s['existing_value']}` |")
        report_lines.append("")

    if unmatched:
        report_lines.append("---")
        report_lines.append("")
        report_lines.append(f"## Unmatched Pages ({total_unmatched})")
        report_lines.append("")
        report_lines.append("| Wiki File | Wiki Title | Settings Count |")
        report_lines.append("|---|---|---|")
        for um in sorted(unmatched, key=lambda x: x["wiki_file"]):
            report_lines.append(f"| {um['wiki_file']} | {um['wiki_title']} | {len(um['settings'])} |")
        report_lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    logger.info(f"Report written to {output_path}")

    print()
    print("=" * 60)
    print("  Sync Summary")
    print("=" * 60)
    print(f"  Wiki pages scanned:   {total_wiki}")
    print(f"  Existing TOML files:  {total_toml}")
    print(f"  New games found:      {total_new}")
    print(f"  Missing settings:     {total_missing}")
    print(f"  Different values:     {total_different}")
    print(f"  Unmatched pages:      {total_unmatched}")
    print(f"  Report:               {output_path}")
    if args.output_files:
        print(f"  TOML output dir:      {Path(args.output_files).resolve()}")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
