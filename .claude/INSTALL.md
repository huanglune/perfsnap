# Install perfsnap for Claude Code

Follow these steps exactly to install or update the skill:

## Step 1: Clone to a temporary directory and copy the skill

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
TMP_DIR="$(mktemp -d)"
git clone https://github.com/huanglune/perfsnap.git "$TMP_DIR/perfsnap"

mkdir -p "$CLAUDE_DIR/skills"
rm -rf "$CLAUDE_DIR/skills/perfsnap"
cp -r "$TMP_DIR/perfsnap/perfsnap" "$CLAUDE_DIR/skills/perfsnap"

rm -rf "$TMP_DIR"
```

## Step 2: Ensure scripts are executable

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
chmod +x "$CLAUDE_DIR/skills/perfsnap/scripts/collect.sh"
```

## Step 3: Verify prerequisites

```bash
command -v python3 >/dev/null 2>&1 && echo "OK: python3" || echo "MISSING: install python3"
test -r /proc/self/task/$$/children && echo "OK: /proc children interface" || echo "MISSING: kernel must expose /proc/<pid>/task/<tid>/children"
```

## Step 4: Verify

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
test -f "$CLAUDE_DIR/skills/perfsnap/SKILL.md" && echo "OK: skill installed" || echo "FAIL: SKILL.md not found"
```

## Uninstall

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
rm -rf "$CLAUDE_DIR/skills/perfsnap"
```
