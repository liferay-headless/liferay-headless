#!/bin/sh

set -e

TARBALL_URL="https://github.com/liferay-headless/liferay-headless/archive/refs/heads/main.tar.gz"
INSTALL_DIR="$HOME/.liferay-headless"
SKILLS_DIR="$HOME/.claude/skills"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "Downloading skills..."
curl -fsSL "$TARBALL_URL" | tar -xz -C "$tmp"

rm -rf "$INSTALL_DIR"
mv "$tmp"/liferay-headless-* "$INSTALL_DIR"

mkdir -p "$SKILLS_DIR"

for skill in "$INSTALL_DIR"/.claude/skills/*/; do
  [ -d "$skill" ] || continue
  name=$(basename "$skill")
  target="$SKILLS_DIR/$name"

  if [ -L "$target" ]; then
    rm "$target"
  elif [ -e "$target" ]; then
    echo "Skipping $name: $target already exists and is not a symlink."
    continue
  fi

  ln -s "$skill" "$target"
  echo "Installed skill: $name"
done

echo "Installation complete. Run 'claude' and try one of the skills (e.g. /retro)."
