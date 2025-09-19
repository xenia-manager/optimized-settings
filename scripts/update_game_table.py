import os
import requests
import json
import re
import logging
from git import Repo  # Ensure GitPython is installed

# ─── Configuration ──────────────────────────────────────────────────────────────
repo_path = os.getcwd()  # Path to the repository
directory_to_scan = "settings"
readme_file = "README.md"

# ─── Logging Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("update_game_table")

# ─── Initialize Repo ───────────────────────────────────────────────────────────
try:
    repo = Repo(repo_path)
    logger.info("Git repo initialized at %s", repo_path)
    
    # Debug: Show current HEAD and branch info
    logger.info("Current HEAD: %s", repo.head.commit.hexsha)
    logger.info("Active branch: %s", repo.active_branch.name if repo.active_branch else "detached")
    
    # Check if we have full history
    total_commits = list(repo.iter_commits())
    logger.info("Total commits accessible: %d", len(total_commits))
    
except Exception as e:
    logger.error("Failed to initialize Git repo: %s", e)
    raise

# ─── Load JSON from URL ─────────────────────────────────────────────────────────
json_url = "https://xenia-manager.github.io/x360db/games.json"

logger.info("Loading JSON data from URL: %s", json_url)
try:
    r = requests.get(json_url, timeout=15)
    r.raise_for_status()
    games_data = r.json()
    logger.info("Loaded %d game entries from remote URL", len(games_data))
except Exception as e:
    logger.error("Failed to load JSON from URL: %s", e)
    raise

# ─── Build Title Lookup ────────────────────────────────────────────────────────
title_lookup = {}
for game in games_data:
    main_id = game.get("id")
    title = game.get("title", "Unknown Title")
    if main_id:
        title_lookup[main_id] = title
    for alt in game.get("alternative_id", []):
        title_lookup[alt] = title
logger.debug("Title lookup contains %d IDs", len(title_lookup))

# ─── Ensure Assets Directory ───────────────────────────────────────────────────
assets_dir = os.path.join(repo_path, "assets")
os.makedirs(assets_dir, exist_ok=True)
logger.info("Assets directory is %s", assets_dir)

# ─── Icon Downloading Function ─────────────────────────────────────────────────
def get_local_icon(tid):
    filename = f"{tid}.png"
    filepath = os.path.join(assets_dir, filename)
    if not os.path.exists(filepath):
        primary_url = f"http://www.xboxunity.net/Resources/Lib/Icon.php?tid={tid}"
        fallback_url = f"https://raw.githubusercontent.com/xenia-manager/x360db/main/titles/{tid}/artwork/icon.png"
        
        urls_to_try = [primary_url, fallback_url]
        for url in urls_to_try:
            logger.debug("Attempting to download icon for %s from %s", tid, url)
            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                with open(filepath, "wb") as f:
                    f.write(r.content)
                logger.info("Saved icon for %s: %s", tid, filepath)
                break
            except Exception as e:
                logger.warning("Failed to download icon from %s: %s", url, e)
    else:
        logger.debug("Icon already cached: %s", filepath)
    return f"assets/{filename}"


# ─── HTML Row Generation ──────────────────────────────────────────────────────
def generate_html_row(filename, last_commit, commit_link):
    name = os.path.splitext(filename)[0]
    icon_path = get_local_icon(name)
    title = title_lookup.get(name, "Unknown Title")
    file_link = (
        "https://github.com/xenia-manager/optimized-settings/"
        f"blob/main/settings/{filename}"
    )
    html = (
        "<tr>"
        f"<td><img src=\"{icon_path}\"/></td>"
        f"<td><center><a href=\"{file_link}\"><strong>{name}</strong></a></center></td>"
        f"<td><center><strong>{title}</strong></center></td>"
        f"<td><center><a href=\"{commit_link}\">{last_commit}</a></center></td>"
        "</tr>"
    )
    return {"html": html, "title": title}

# ─── Scan Directory ────────────────────────────────────────────────────────────
rows = []
directory_path = os.path.join(repo_path, directory_to_scan)
logger.info("Scanning directory: %s", directory_path)

for root, _, files in os.walk(directory_path):
    for file in files:
        rel_path = os.path.relpath(os.path.join(root, file), repo_path)
        logger.debug("Processing file: %s", rel_path)
        
        try:
            # Get commits for this specific file path
            commits = list(repo.iter_commits(paths=rel_path, max_count=10))
            logger.debug("Found %d commits for %s", len(commits), rel_path)
            
            if not commits:
                logger.warning("No commits found for %s", rel_path)
                # Fallback: use current date and HEAD commit
                commit = repo.head.commit
                date_str = commit.committed_datetime.strftime("%d/%m/%Y")
                link = f"{repo.remotes.origin.url.rstrip('.git')}/commit/{commit.hexsha}"
                logger.info("Using HEAD commit for %s: %s", rel_path, date_str)
            else:
                commit = commits[0]  # Most recent commit
                date_str = commit.committed_datetime.strftime("%d/%m/%Y")
                link = f"{repo.remotes.origin.url.rstrip('.git')}/commit/{commit.hexsha}"
                logger.debug("Last modified %s on %s (commit: %s)", rel_path, date_str, commit.hexsha[:8])
                
                # Debug: Show commit history for first few files
                if len(rows) < 3:
                    logger.info("Commit history for %s:", rel_path)
                    for i, c in enumerate(commits[:3]):
                        logger.info("  %d: %s - %s", i+1, c.committed_datetime.strftime("%d/%m/%Y"), c.hexsha[:8])
            
            rows.append(generate_html_row(file, date_str, link))
            
        except Exception as e:
            logger.error("Error processing %s: %s", rel_path, e)
            continue

logger.info("Collected %d rows", len(rows))

# ─── Sort and Build Table ─────────────────────────────────────────────────────
sorted_rows = sorted(rows, key=lambda r: r["title"].lower())
new_table = (
    "<table id=\"games-table\" align=\"center\">"
    "<thead><tr><th></th><th>Title Id</th><th>Title</th><th>Last Modified</th></tr></thead>"
    "<tbody>"
    + "".join(r["html"] for r in sorted_rows)
    + "</tbody></table>"
)
logger.debug("Generated new HTML table with %d entries", len(sorted_rows))

# ─── Read, Replace, Write README ───────────────────────────────────────────────
try:
    with open(readme_file, "r", encoding="utf-8", errors="replace") as f:
        readme_content = f.read()
    logger.info("Read README.md (%d characters)", len(readme_content))
except Exception as e:
    logger.error("Error reading README.md: %s", e)
    raise

table_pattern = r"(<table id=\"games-table\" align=\"center\">.*?</table>)"
updated_readme = re.sub(table_pattern, new_table, readme_content, flags=re.DOTALL)
logger.info("Replaced games table in README.md")

try:
    with open(readme_file, "w", encoding="utf-8", errors="replace") as f:
        f.write(updated_readme)
    logger.info("Wrote updated README.md (%d characters)", len(updated_readme))
except Exception as e:
    logger.error("Error writing README.md: %s", e)
    raise

logger.info("README.md updated with the new games table.")