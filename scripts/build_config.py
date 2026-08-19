#!/usr/bin/env python3
"""Build config.toml from config.example.toml with secrets from environment variables.

Reads config.example.toml, performs targeted key replacements using values
from environment variables, and writes the result to config.toml.  Only
stdlib modules are used so this script runs before ``uv sync``.

Usage (in GitHub Actions):
    GROQ_API_KEY=xxx PEXELS_API_KEY=yyy python scripts/build_config.py

Required env vars:  GROQ_API_KEY, PEXELS_API_KEY
Optional env vars:  PIXABAY_API_KEY, COVERR_API_KEY
"""

from __future__ import annotations

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_CONFIG = os.path.join(PROJECT_ROOT, "config.example.toml")
OUTPUT_CONFIG = os.path.join(PROJECT_ROOT, "config.toml")


def _replace_toml_value(content: str, key: str, new_value: str) -> str:
    """Replace a top-level TOML key's value using a regex on the raw text.

    This deliberately operates on *text*, not a parsed TOML tree, so
    comments, ordering, and formatting from the example file are preserved.
    The regex matches ``key = <anything-to-end-of-line>`` and replaces
    only the value portion.
    """
    pattern = rf"^({re.escape(key)}\s*=\s*).*$"
    result, count = re.subn(pattern, rf"\g<1>{new_value}", content, flags=re.MULTILINE)
    if count == 0:
        print(f"WARNING: key '{key}' not found in config template", file=sys.stderr)
    return result


def _require_env(name: str) -> str:
    """Return the value of a required environment variable or exit."""
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERROR: {name} environment variable is required", file=sys.stderr)
        sys.exit(1)
    return value


def main() -> None:
    if not os.path.isfile(EXAMPLE_CONFIG):
        print(f"ERROR: {EXAMPLE_CONFIG} not found", file=sys.stderr)
        sys.exit(1)

    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as f:
        content = f.read()

    # ── LLM Provider ────────────────────────────────────────────────────
    groq_key = _require_env("GROQ_API_KEY")
    content = _replace_toml_value(content, "llm_provider", '"groq"')
    content = _replace_toml_value(content, "groq_api_key", f'"{groq_key}"')
    content = _replace_toml_value(content, "groq_model_name", '"openai/gpt-oss-120b"')

    # ── Video Source (Pexels — required) ────────────────────────────────
    pexels_key = _require_env("PEXELS_API_KEY")
    content = _replace_toml_value(content, "video_source", '"pexels"')
    content = _replace_toml_value(content, "pexels_api_keys", f'["{pexels_key}"]')

    # ── Optional backup video sources ───────────────────────────────────
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if pixabay_key:
        content = _replace_toml_value(content, "pixabay_api_keys", f'["{pixabay_key}"]')

    coverr_key = os.environ.get("COVERR_API_KEY", "").strip()
    if coverr_key:
        content = _replace_toml_value(content, "coverr_api_keys", f'["{coverr_key}"]')

    # ── Subtitles (Edge TTS — free, no GPU) ─────────────────────────────
    content = _replace_toml_value(content, "subtitle_provider", '"edge"')

    # ── Disable Upload-Post (we use direct YouTube upload) ──────────────
    content = _replace_toml_value(content, "upload_post_enabled", "false")
    content = _replace_toml_value(content, "upload_post_auto_upload", "false")

    # ── Write the final config ──────────────────────────────────────────
    with open(OUTPUT_CONFIG, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✓ config.toml written ({len(content)} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
