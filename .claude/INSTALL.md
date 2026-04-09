# Install capture-performance-metrics for Claude Code

Follow these steps exactly to install or update the skill:

## Step 1: Detect Claude Code config directory

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
```

## Step 2: Clone or update the repository

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
REPO_DIR="$CLAUDE_DIR/repos/capture-performance-metrics"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull
else
  git clone git@github.com:huanglune/capture-performance-metrics.git "$REPO_DIR"
fi
```

## Step 3: Create the skill symlink

This is idempotent — safe to run on both install and update:

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
REPO_DIR="$CLAUDE_DIR/repos/capture-performance-metrics"
mkdir -p "$CLAUDE_DIR/skills"
ln -sf "$REPO_DIR/capture-performance-metrics" "$CLAUDE_DIR/skills/capture-performance-metrics"
```

## Step 4: Ensure scripts are executable

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
chmod +x "$CLAUDE_DIR/skills/capture-performance-metrics/scripts/collect_pidstat.sh"
```

## Step 5: Verify prerequisites

```bash
command -v pidstat >/dev/null 2>&1 && echo "OK: pidstat" || echo "MISSING: sudo apt install sysstat"
command -v pgrep  >/dev/null 2>&1 && echo "OK: pgrep"  || echo "MISSING: sudo apt install procps"
command -v python3 >/dev/null 2>&1 && echo "OK: python3" || echo "MISSING: install python3"
```

## Step 6: Verify

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
test -f "$CLAUDE_DIR/skills/capture-performance-metrics/SKILL.md" && echo "OK: skill installed" || echo "FAIL: SKILL.md not found"
```

## Uninstall

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
rm -f "$CLAUDE_DIR/skills/capture-performance-metrics"
rm -rf "$CLAUDE_DIR/repos/capture-performance-metrics"
```
