# Install perfsnap for Codex

Follow these steps exactly to install or update the skill:

## Step 1: Clone to a temporary directory and copy the skill

```bash
TMP_DIR="$(mktemp -d)"
git clone https://github.com/huanglune/perfsnap.git "$TMP_DIR/perfsnap"

mkdir -p ~/.codex/skills
rm -rf ~/.codex/skills/perfsnap
cp -r "$TMP_DIR/perfsnap/perfsnap" ~/.codex/skills/perfsnap

mkdir -p ~/.agents/skills
rm -rf ~/.agents/skills/perfsnap
cp -r "$TMP_DIR/perfsnap/perfsnap" ~/.agents/skills/perfsnap

rm -rf "$TMP_DIR"
```

## Step 2: Ensure scripts are executable

```bash
chmod +x ~/.codex/skills/perfsnap/scripts/collect_pidstat.sh
chmod +x ~/.agents/skills/perfsnap/scripts/collect_pidstat.sh
```

## Step 3: Verify prerequisites

```bash
command -v pidstat >/dev/null 2>&1 && echo "OK: pidstat" || echo "MISSING: sudo apt install sysstat"
command -v pgrep  >/dev/null 2>&1 && echo "OK: pgrep"  || echo "MISSING: sudo apt install procps"
command -v python3 >/dev/null 2>&1 && echo "OK: python3" || echo "MISSING: install python3"
```

## Step 4: Verify

```bash
test -f ~/.codex/skills/perfsnap/SKILL.md && echo "OK: codex skill installed" || echo "FAIL: ~/.codex/skills missing"
test -f ~/.agents/skills/perfsnap/SKILL.md && echo "OK: agents skill installed" || echo "FAIL: ~/.agents/skills missing"
```

## Uninstall

```bash
rm -rf ~/.codex/skills/perfsnap
rm -rf ~/.agents/skills/perfsnap
```
