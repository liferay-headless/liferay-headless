#!/bin/sh

set -e

INSTALL_DIR="$HOME/.liferay-headless"
SKILLS_DIR="$HOME/.claude/skills"

if [ -d "$SKILLS_DIR" ]; then
  for link in "$SKILLS_DIR"/*; do
    [ -L "$link" ] || continue
    target=$(readlink "$link")
    case "$target" in
      "$INSTALL_DIR"/*)
        rm "$link"
        echo "Removed skill: $(basename "$link")"
        ;;
    esac
  done
fi

rm -rf "$INSTALL_DIR"

echo "Uninstall complete."
