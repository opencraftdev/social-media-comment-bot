#!/usr/bin/env bash
# Source this file to pin the Claude Code CLI to the OpenCraft account
# for the current shell session.
#
# Usage:
#   source scripts/use-opencraft-account.sh
#   claude   # now uses ~/.claude-opencraft credentials
#
# First-time setup: after sourcing, run `claude` and `/login` once with
# opencraft.dev@gmail.com. Credentials persist in ~/.claude-opencraft.

export CLAUDE_CONFIG_DIR="$HOME/.claude-opencraft"
echo "CLAUDE_CONFIG_DIR -> $CLAUDE_CONFIG_DIR (OpenCraft account)"
