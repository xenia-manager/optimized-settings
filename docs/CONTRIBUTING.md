# Xenia Canary Optimized Settings Guide

This guide explains how to write optimized settings for Xenia Emulator based on real game-specific configurations.

---

## Table of Contents

1. [How to Contribute](#how-to-contribute)
2. [Understanding the Config Structure](#understanding-the-config-structure)
3. [Game-Specific Examples](#game-specific-examples)
4. [Best Practices](#best-practices)

---

## Understanding the Config Structure

Xenia Canary uses a TOML-based configuration file with the following sections:

```toml
[APU]
# Settings go here
[CPU]
# Settings go here
[Config]
# Settings go here
[Content]
# Settings go here
[D3D12]
[Display]
[GPU]
[General]
[HACKS]
[HID]
[Kernel]
[Live]
[Logging]
[Memory]
[MouseHook]
[Profiles]
[SDL]
[Storage]
[UI]
[Video]
[Vulkan]
[Win32]
[XConfig]
[x64]
```

---

## Game-Specific Examples

### Example: `Forza Horizon`

```toml
[APU]
use_dedicated_xma_thread = false # Fixes Audio.
xma_decoder = "new" # Fixes Audio.

[GPU]
clear_memory_page_state = true # Fixes warped graphics in game.
framerate_limit = 120 # Caps the FPS to 60.
gpu_allow_invalid_fetch_constants = true # Fixes missing mirrors.
readback_resolve = "full" # Fixes designs and thumbnails of cars at the cost of performance.
vsync = false # Unlocks FPS

[General]
controller_hotkeys = true # Turn off Readback Resolve with A + Guide Button when the car thumbnails work.

[Storage]
mount_cache = true # Stops the game from crashing when starting a race.
```

**Problems Fixed:**

- Audio playback issues
- Warped graphics on cars/tracks
- Missing rear-view mirrors
- Car thumbnails and designs in menus
- Crashes when starting races

**Performance Tip:** Use `controller_hotkeys` to toggle `readback_resolve` off during gameplay (A + Guide button) for better FPS once menus are navigated.

## Best Practices

### 1. Start Minimal

Begin with an empty template and only add settings that fix specific issues:

```toml
[GPU]
# Add only what you need
framerate_limit = 120
```

### 2. Comment Your Changes

Always add comments explaining why a setting was changed:

```toml
[GPU]
readback_resolve = "full" # Fixes car thumbnails in menus
```

### 3. File Naming Convention

Name config files after the game's Title ID (Prioritize using `id` from `x360db` unless the fix only applies to game demo which has it's `id` in `alternative_ids`):

- `4D5309C9.toml` = Forza Horizon
- `5454082B.toml` = Red Dead Redemption

Find Title IDs on [x360db](https://github.com/xenia-manager/x360db/blob/main/games.json) or [Xenia Compatibility](https://github.com/xenia-canary/game-compatibility/issues).

---

## Quick Reference Template

```toml
# Title Name
# Title ID

[APU]
use_dedicated_xma_thread = false # Fixes audio.
xma_decoder = "new" # Fixes audio.

[GPU]
clear_memory_page_state = true                    # Warped graphics.
framerate_limit = 120                             # 60 FPS cap.
gpu_allow_invalid_fetch_constants = true          # Missing reflections.
readback_resolve = "full"                         # Broken UI/thumbnails.
vsync = false                                     # Unlock FPS.
query_occlusion_sample_lower_threshold = -1       # Light bleeding.

[Memory]
protect_zero = false                              # Freezing issues.

[Storage]
mount_cache = true                                # Crash on load.

[General]
controller_hotkeys = true                         # Toggle settings in-game.
```

---

## How to Contribute

### Ways to Contribute

You can contribute to this project in several ways:

1. **Submit Game Configurations** - Share optimized settings for games you've tested
2. **Improve Existing Configs** - Refine settings for better performance or compatibility
3. **Report Issues** - Document problems with current configurations
4. **Update Documentation** - Help improve guides and examples

### Steps to Add a Game Configuration

1. **Test the Game** - Run the game with default settings and note any issues (audio, graphics, crashes, etc.)

2. **Identify Fixes** - Experiment with config settings to resolve each issue

3. **Create the Config File** - Name it using the Title ID format (e.g., `4D5309C9.toml`)

4. **Document Your Changes** - Add comments explaining what each setting fixes:

   ```toml
   [GPU]
   readback_resolve = "full" # Fixes car thumbnails in menus
   ```

5. **Test Thoroughly** - Verify all fixes work and don't introduce new problems

6. **Submit Your Config** - Place the file in the `settings/` directory and create a pull request

### Contribution Guidelines

- **Test on Real Hardware** - Ensure settings work across different GPU vendors (NVIDIA, AMD, Intel)
- **Prioritize Performance** - Only use performance-heavy settings when necessary for visual fixes
- **Keep Comments Clear** - Explain _why_ a setting was changed, not just _what_ it does
- **Follow Naming Conventions** - Use Title IDs from [x360db](https://github.com/xenia-manager/x360db/blob/main/games.json)
- **Include Problem List** - Document all issues your config fixes in the PR description

---

## Pull Request Process

### 1. Fork & Branch

- Fork the repository
- Create a new branch

### 2. Add Configuration

- Add your `.toml` file/files to the `settings/` directory

### 3. Submit a Pull Request

#### Single Game

- **Title:** `feat(addition)/refactor(improvement): Added/Improved [TitleID] <Game Title>`
- **Message:** List of fixes applied with notes

#### Multiple Games

- **Title:** `feat(addition)/refactor(improvements): Added/Improved <number> Game Settings`
- **Message:**
  - `[TitleID] <Game 1 Title>`: List of fixes with notes
  - `[TitleID] <Game 2 Title>`: List of fixes with notes
  <br>.<br>.<br>.

---

## Resources

- [x360db GitHub](https://github.com/xenia-manager/x360db)
- [Xenia Canary Compatibility List](https://github.com/xenia-canary/game-compatibility/issues)
- [TOML Configuration Format](https://toml.io/)
