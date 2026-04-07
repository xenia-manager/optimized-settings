#!/usr/bin/env python3
"""Convert all TOML files in settings folder to a single JSON file for searching."""

import json
from datetime import timezone
from pathlib import Path
from git import Repo


def get_last_modified_date(repo, file_path):
    """Get last modified date from Git commit history for a specific file."""
    try:
        rel_path = str(file_path.relative_to(repo.working_dir))
        commits = list(repo.iter_commits(paths=rel_path, max_count=1))

        if commits:
            commit = commits[0]
            return commit.committed_datetime.strftime("%Y-%m-%d")
        else:
            # Fallback: use HEAD commit date if no commits found for this file
            commit = repo.head.commit
            return commit.committed_datetime.strftime("%Y-%m-%d")
    except Exception:
        # Fallback: use filesystem mtime if Git lookup fails
        mtime = file_path.stat().st_mtime
        from datetime import datetime

        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")


def main():
    script_dir = Path(__file__).parent.resolve()
    root_dir = script_dir.parent
    settings_dir = root_dir / "settings"
    output_dir = root_dir / "data"
    output_file = output_dir / "settings.json"

    # Ensure output directory exists
    output_dir.mkdir(exist_ok=True)

    # Initialize Git repo
    repo = Repo(root_dir)

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

        # Get last modified date from Git
        last_modified = get_last_modified_date(repo, toml_file)

        settings_list.append(
            {"id": file_id, "title": title, "last_modified": last_modified}
        )

    # Write JSON output
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(settings_list, f, indent=2, ensure_ascii=False)

    print(f"Generated {output_file} with {len(settings_list)} entries")


if __name__ == "__main__":
    main()
