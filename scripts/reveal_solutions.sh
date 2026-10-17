#!/usr/bin/env bash
# Instructor / catch-up: drop in the finished OpenAI adapter.
set -euo pipefail
cd "$(dirname "$0")/.."
cp rebookr/llm/openai_provider.py rebookr/llm/openai_provider.py.mine
cp solutions/openai_provider.py rebookr/llm/openai_provider.py
echo "✓ OpenAI adapter replaced with the solution. Run: pytest -q"
echo "  Your own version is saved as rebookr/llm/openai_provider.py.mine"
