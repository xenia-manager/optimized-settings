#!/usr/bin/env python3
"""Convert all TOML files in settings folder to a single JSON file for searching."""

import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    script_dir = Path(__file__).parent.resolve()
    root_dir = script_dir.parent
    settings_dir = root_dir / "settings"
    output_dir = root_dir / "data"
    output_file = output_dir / "settings.json"

    # Ensure output directory exists
    output_dir.mkdir(exist_ok=True)

    settings_list = []

    # Process all .toml files in settings directory
    for toml_file in sorted(settings_dir.glob("*.toml")):
        file_id = toml_file.stem  # Filename without extension

        # Read and parse TOML content to extract title
        content = toml_file.read_text(encoding="utf-8")

        # Extract title from comment (first line format: # Title Name: <title>)
        title = file_id  # Default to file ID
        for line in content.split("\n"):
            if line.startswith("# Title Name:"):
                title = line.split(":", 1)[1].strip()
                break

        # Get last modified date
        mtime = toml_file.stat().st_mtime
        last_modified = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")

        settings_list.append({
            "id": file_id,
            "title": title,
            "last_modified": last_modified
        })

    # Write JSON output
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(settings_list, f, indent=2, ensure_ascii=False)

    print(f"Generated {output_file} with {len(settings_list)} entries")


if __name__ == "__main__":
    main()
