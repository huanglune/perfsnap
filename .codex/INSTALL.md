# Install capture-performance-metrics for Codex

Follow these steps exactly to install or update the skill:

## Step 1: Clone or update the repository

```bash
REPO_DIR="$HOME/.codex/capture-performance-metrics"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull
else
  git clone git@github.com:huanglune/capture-performance-metrics.git "$REPO_DIR"
fi
```

## Step 2: Create the skills symlink

```bash
mkdir -p ~/.agents/skills
ln -sf ~/.codex/capture-performance-metrics/capture-performance-metrics ~/.agents/skills/capture-performance-metrics
```

## Step 3: Ensure scripts are executable

```bash
chmod +x ~/.agents/skills/capture-performance-metrics/scripts/collect_pidstat.sh
```

## Step 4: Verify prerequisites

```bash
command -v pidstat >/dev/null 2>&1 && echo "OK: pidstat" || echo "MISSING: sudo apt install sysstat"
command -v pgrep  >/dev/null 2>&1 && echo "OK: pgrep"  || echo "MISSING: sudo apt install procps"
command -v python3 >/dev/null 2>&1 && echo "OK: python3" || echo "MISSING: install python3"
```

## Step 5: Verify

```bash
test -f ~/.agents/skills/capture-performance-metrics/SKILL.md && echo "OK: skill installed" || echo "FAIL: SKILL.md not found"
```

## Uninstall

```bash
rm -f ~/.agents/skills/capture-performance-metrics
rm -rf ~/.codex/capture-performance-metrics
```
