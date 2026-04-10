# Install perfsnap for Codex

Follow these steps exactly to install or update the skill:

## Step 1: Clone or update the repository

```bash
REPO_DIR="$HOME/.codex/perfsnap"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull
else
  git clone git@github.com:huanglune/perfsnap.git "$REPO_DIR"
fi
```

## Step 2: Create the skills symlinks

```bash
mkdir -p ~/.codex/skills
ln -sf ~/.codex/perfsnap/perfsnap ~/.codex/skills/perfsnap

mkdir -p ~/.agents/skills
ln -sf ~/.codex/perfsnap/perfsnap ~/.agents/skills/perfsnap
```

## Step 3: Ensure scripts are executable

```bash
chmod +x ~/.codex/perfsnap/perfsnap/scripts/collect_pidstat.sh
```

## Step 4: Verify prerequisites

```bash
command -v pidstat >/dev/null 2>&1 && echo "OK: pidstat" || echo "MISSING: sudo apt install sysstat"
command -v pgrep  >/dev/null 2>&1 && echo "OK: pgrep"  || echo "MISSING: sudo apt install procps"
command -v python3 >/dev/null 2>&1 && echo "OK: python3" || echo "MISSING: install python3"
```

## Step 5: Verify

```bash
test -f ~/.codex/skills/perfsnap/SKILL.md && echo "OK: codex skill installed" || echo "FAIL: ~/.codex/skills symlink missing"
test -f ~/.agents/skills/perfsnap/SKILL.md && echo "OK: agents skill installed" || echo "FAIL: ~/.agents/skills symlink missing"
```

## Uninstall

```bash
rm -f ~/.codex/skills/perfsnap
rm -f ~/.agents/skills/perfsnap
rm -rf ~/.codex/perfsnap
```
