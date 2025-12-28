# Pre-commit Configuration

This repository uses [pre-commit](https://pre-commit.com/) to automatically lint, format, and validate code before commits.

## Configured Hooks

### 1. **Ruff** (Python)
- **Linter**: `ruff-check` - Checks Python code with auto-fix
- **Formatter**: `ruff-format` - Formats Python code
- **Files**: `*.py`, `*.pyi`

### 2. **Biome** (JavaScript)
- **Check & Format**: `biome-check` - Lints and formats JavaScript
- **Files**: `bins-website/*.js`, `bins-website/worker/*.js`
- **Configuration**: `bins-website/biome.json`

### 3. **Regenerate councils-data.json**
- **Purpose**: Automatically regenerates `bins-website/councils-data.json` from YAML files
- **Trigger**: When any `src/councils/*.yaml` file is modified
- **Command**: `uv run python bins-website/convert-yaml.py`

### 4. **Check councils-data.json is staged**
- **Purpose**: Ensures `bins-website/councils-data.json` is staged when YAML files change
- **Trigger**: Always runs on commit
- **Script**: `.pre-commit-scripts/check-councils-json.sh`

## Installation

```bash
# Install pre-commit (if not already installed)
pip install pre-commit
# or: brew install pre-commit

# Install the git hook scripts
pre-commit install
```

## Usage

### Automatic (Recommended)

Pre-commit runs automatically on `git commit`. If issues are found:
1. Hooks will auto-fix what they can
2. You'll need to stage the changes: `git add .`
3. Retry the commit: `git commit`

### Manual

```bash
# Run on all files
pre-commit run --all-files

# Run on specific files
pre-commit run --files src/bin_lookup.py

# Run a specific hook
pre-commit run ruff-check --all-files
pre-commit run biome-check --all-files
pre-commit run regenerate-councils-json
```

## Workflow Examples

### Modifying a Council YAML File

```bash
# 1. Edit a council file
vim src/councils/BristolCityCouncil.yaml

# 2. Stage the change
git add src/councils/BristolCityCouncil.yaml

# 3. Commit (pre-commit will automatically run)
git commit -m "Update Bristol council config"

# Pre-commit will:
# - Run ruff on any Python files
# - Regenerate bins-website/councils-data.json
# - Check that councils-data.json is staged (will fail if not!)

# 4. If check fails, stage the generated JSON and retry
git add bins-website/councils-data.json
git commit -m "Update Bristol council config"
```

### Modifying JavaScript Files

```bash
# 1. Edit JavaScript
vim bins-website/app.js

# 2. Stage and commit
git add bins-website/app.js
git commit -m "Update app logic"

# Pre-commit will:
# - Run Biome check (lint + format)
# - Auto-fix any issues
# - If changes were made, you'll need to stage and retry
```

## Configuration Files

- `.pre-commit-config.yaml` - Main configuration
- `bins-website/biome.json` - Biome (JavaScript) settings
- `.pre-commit-scripts/` - Helper scripts for custom hooks

## Bypassing Hooks (Not Recommended)

```bash
# Skip all hooks for a single commit
git commit --no-verify

# Only use this for emergencies!
```

## Updating Hooks

```bash
# Update to latest versions
pre-commit autoupdate

# Re-install hooks after updates
pre-commit install
```

## Troubleshooting

### "Hook failed" - What to do?

1. **Read the error message** - It tells you what failed
2. **Auto-fixes**: If files were modified, stage them: `git add .`
3. **Manual fixes**: Fix the issue, stage, and retry
4. **Regenerate check fails**: Run `uv run python bins-website/convert-yaml.py` then stage

### Common Issues

**Issue**: `ModuleNotFoundError: No module named 'yaml'`
- **Solution**: Ensure you're using `uv run python` for the conversion script

**Issue**: Biome changes tabs/quotes
- **Solution**: This is expected! Biome enforces consistent style (tabs, double quotes)

**Issue**: councils-data.json check fails
- **Solution**: Run `uv run python bins-website/convert-yaml.py` and stage the JSON file

## Benefits

- ✅ **Consistent code style** across Python and JavaScript
- ✅ **Auto-fix common issues** before they reach GitHub
- ✅ **Prevents outdated JSON** from being deployed
- ✅ **Catches bugs early** with linting
- ✅ **Fast** - Only runs on changed files
