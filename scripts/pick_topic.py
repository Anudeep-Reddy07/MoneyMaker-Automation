#!/usr/bin/env python3
"""Pick a non-repeating video topic from a curated static list.

Reads topic_history.json to avoid recent topics, picks a fresh one,
and prints the chosen topic to stdout. The history file is updated
in place so the workflow can commit it back to the repo.

Usage:
    python scripts/pick_topic.py
    # → prints one topic line to stdout

Environment variables:
    TOPIC_HISTORY_FILE  Override the default history file path.
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timezone

HISTORY_FILE = os.environ.get(
    "TOPIC_HISTORY_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "topic_history.json"),
)

# Exclude this many recent topics from the random pool to avoid repeats.
LOOKBACK = 15

# ---------------------------------------------------------------------------
# Curated topics across 4 categories (~60 total).
# Each string is passed directly to --video-subject, so keep them punchy
# and broad enough for Pexels footage to match.
# ---------------------------------------------------------------------------
TOPICS: list[str] = [
    # ── AI & Technology ──────────────────────────────────────────────────
    "How AI is quietly changing everyday life",
    "The rise of AI-generated music and art",
    "Why self-driving cars are taking so long",
    "How ChatGPT actually works explained simply",
    "5 AI tools that save hours every week",
    "The dark side of deepfake technology",
    "How AI is revolutionizing healthcare diagnosis",
    "Why quantum computing matters for the future",
    "The hidden AI behind your social media feed",
    "How robots are transforming warehouse logistics",
    "The future of AI in education and learning",
    "How brain-computer interfaces could change everything",
    "Why cybersecurity is more important than ever",
    "The surprising ways AI is used in agriculture",
    "How 3D printing is reshaping manufacturing",
    # ── Finance & Wealth ─────────────────────────────────────────────────
    "5 money habits of self-made millionaires",
    "Why most people never build real wealth",
    "The psychology behind impulsive spending",
    "How compound interest makes you rich over time",
    "Passive income ideas that actually work in 2025",
    "The biggest financial mistakes people make in their 20s",
    "How to build an emergency fund from scratch",
    "Why the stock market always recovers eventually",
    "The simple budgeting rule that changed everything",
    "How inflation quietly destroys your savings",
    "Why financial literacy should be taught in schools",
    "The truth about cryptocurrency investing",
    "How to negotiate a higher salary at your job",
    "The real cost of subscription services you forgot about",
    "Why starting to invest early beats investing more later",
    # ── Self-Improvement & Productivity ──────────────────────────────────
    "The 2-minute rule that fixes procrastination",
    "Why waking up at 5 AM will not make you successful",
    "How to build a habit that actually sticks",
    "The science of motivation and why willpower fails",
    "Why reading books changes your brain permanently",
    "How to stay focused in a world full of distractions",
    "The Pomodoro technique and why it works so well",
    "Why journaling is the most underrated productivity tool",
    "How to stop overthinking and start doing",
    "The power of saying no to almost everything",
    "Why your morning routine matters more than you think",
    "How to learn any new skill in 30 days",
    "The science of sleep and why 8 hours is non-negotiable",
    "Why perfectionism is actually holding you back",
    "How to build unshakable confidence in 90 days",
    # ── Science & Nature ─────────────────────────────────────────────────
    "Why the ocean is still mostly unexplored",
    "How your brain creates dreams while you sleep",
    "The fascinating science behind black holes",
    "Why honey never spoils even after thousands of years",
    "How trees communicate through underground networks",
    "The science of why music gives you chills",
    "Why we still cannot predict earthquakes accurately",
    "How the human body fights viruses without you knowing",
    "The incredible journey of a single raindrop",
    "Why some animals can survive in extreme environments",
    "How your gut bacteria control your mood and health",
    "The mystery of dark matter and dark energy",
    "Why the northern lights happen and where to see them",
    "How volcanoes shaped the world we live in today",
    "The surprising intelligence of crows and ravens",
]


def load_history() -> list[dict]:
    """Load the topic history from disk."""
    if not os.path.isfile(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("history", [])
    except (json.JSONDecodeError, KeyError):
        return []


def save_history(history: list[dict]) -> None:
    """Persist the updated topic history to disk."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump({"history": history}, f, indent=2, ensure_ascii=False)
        f.write("\n")


def pick_topic() -> str:
    """Select a topic that hasn't been used in the last LOOKBACK runs."""
    history = load_history()
    recent_topics = {entry["topic"] for entry in history[-LOOKBACK:]}

    available = [t for t in TOPICS if t not in recent_topics]

    # If every topic has been used recently, reset by only excluding the
    # single most-recent topic so we never repeat back-to-back.
    if not available:
        last_topic = history[-1]["topic"] if history else ""
        available = [t for t in TOPICS if t != last_topic]

    chosen = random.choice(available)

    # Append to history and persist.
    history.append(
        {
            "topic": chosen,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    save_history(history)

    return chosen


if __name__ == "__main__":
    topic = pick_topic()
    # Only the topic goes to stdout — the workflow captures this.
    print(topic)
    # Human-readable log goes to stderr so it shows in Actions logs.
    print(f"[pick_topic] Selected: {topic}", file=sys.stderr)
