#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTION_SKILLS=(
  remotion-best-practices
  remotion-captions
  remotion-create
  remotion-docs
  remotion-interactivity
  remotion-maps
  remotion-markup
  remotion-multimedia
  remotion-render
  remotion-saas
  remotion-upgrade
)

missing_skills=()

find_missing_skills() {
  missing_skills=()
  local skill_name

  for skill_name in "${REMOTION_SKILLS[@]}"; do
    if [[ ! -f "$ROOT_DIR/.agents/skills/$skill_name/SKILL.md" ]]; then
      missing_skills+=("$skill_name")
    fi
  done
}

find_missing_skills

if (( ${#missing_skills[@]} > 0 )) && [[ "${1:-}" == "--install" ]]; then
  cd "$ROOT_DIR"
  npx skills add remotion-dev/skills --yes
  find_missing_skills
fi

if (( ${#missing_skills[@]} > 0 )); then
  echo "Missing official Remotion skills:"
  for skill_name in "${missing_skills[@]}"; do
    echo "  .agents/skills/$skill_name/SKILL.md"
  done
  cat <<'MSG'

Install the complete bundle with:
  npx skills add remotion-dev/skills --yes

Agents should ask for permission before running this command because it uses network access.
MSG
  exit 1
fi

mkdir -p "$ROOT_DIR/.claude/skills"

for skill_name in "${REMOTION_SKILLS[@]}"; do
  claude_link="$ROOT_DIR/.claude/skills/$skill_name"

  if [[ -e "$claude_link" && ! -L "$claude_link" ]]; then
    echo "Cannot create Claude Code symlink because a non-symlink path exists:"
    echo "  .claude/skills/$skill_name"
    exit 1
  fi
done

for skill_name in "${REMOTION_SKILLS[@]}"; do
  claude_link="$ROOT_DIR/.claude/skills/$skill_name"
  ln -sfn "../../.agents/skills/$skill_name" "$claude_link"
done

echo "OK: verified ${#REMOTION_SKILLS[@]} official Remotion skills and Claude Code symlinks"
