#!/usr/bin/env python3
"""Pick or generate a non-repeating video topic.

Mode 1 (AI Dynamic - Default):
    Calls the Groq LLM to brainstorm a fresh, viral, trending Short topic
    in high-engagement niches (AI/Tech, Finance, Mindset, Science), while
    injecting past history so the AI never repeats an idea.

Mode 2 (Curated Fallback):
    If the LLM is unreachable or GROQ_API_KEY is not set, picks randomly
    from a curated 60-topic library.

The chosen topic is printed to stdout and recorded in topic_history.json.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from datetime import datetime, timezone
import urllib.request
import urllib.error

HISTORY_FILE = os.environ.get(
    "TOPIC_HISTORY_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "topic_history.json"),
)

# Lookback window for history checks
LOOKBACK = 20

# ---------------------------------------------------------------------------
# Curated backup topics (~60 total) used if LLM call is unavailable.
# ---------------------------------------------------------------------------
BACKUP_TOPICS: list[str] = [
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


def generate_topic_with_ai(recent_topics: list[str]) -> str | None:
    """Ask Groq LLM to brainstorm a fresh, viral YouTube Shorts topic."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        import requests
    except ImportError:
        return None

    recent_str = "\n- ".join(recent_topics[-15:]) if recent_topics else "None"
    prompt = (
        "You are an elite YouTube Shorts growth strategist. Brainstorm 1 viral, high-CTR Short video topic.\n"
        "Niches to choose from (pick 1):\n"
        "- AI & Future Technology\n"
        "- Smart Money, Investing & Wealth Psychology\n"
        "- High-Performance Habits & Productivity Hacks\n"
        "- Mindblowing Science & Human Body Secrets\n\n"
        f"DO NOT repeat or closely mirror any of these recently used topics:\n- {recent_str}\n\n"
        "Guidelines:\n"
        "1. Max 7-10 words. Punchy, curiosity-inducing, broad enough for stock video footage to match.\n"
        "2. Return ONLY the topic title text. No quotes, no markdown, no emojis, no commentary."
    )

    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {
                "role": "system",
                "content": "You are a viral YouTube Shorts content strategist. You output only raw video titles.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.85,
        "max_tokens": 200,
    }

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            topic = data["choices"][0]["message"]["content"].strip()
            topic = re.sub(r'^["\'#\*\-\s]+|["\'\s]+$', "", topic)
            if topic and len(topic) > 5 and topic not in recent_topics:
                print(f"[pick_topic] Generated dynamic AI topic: {topic}", file=sys.stderr)
                return topic
        else:
            print(f"[pick_topic] Groq API returned status {resp.status_code}", file=sys.stderr)
    except Exception as exc:
        print(f"[pick_topic] AI topic generation failed ({exc}), falling back to curated list", file=sys.stderr)

    return None


def pick_topic() -> str:
    """Select or generate a non-repeating topic."""
    history = load_history()
    recent_topics = [entry["topic"] for entry in history[-LOOKBACK:] if "topic" in entry]

    # Attempt 1: Dynamic AI generation via Groq LLM
    ai_topic = generate_topic_with_ai(recent_topics)
    if ai_topic:
        chosen = ai_topic
    else:
        # Attempt 2: Fallback to curated static list
        recent_set = set(recent_topics)
        available = [t for t in BACKUP_TOPICS if t not in recent_set]

        if not available:
            last_topic = history[-1]["topic"] if history else ""
            available = [t for t in BACKUP_TOPICS if t != last_topic]

        chosen = random.choice(available)
        print(f"[pick_topic] Picked from backup curated list: {chosen}", file=sys.stderr)

    # Persist in history
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
    # Topic printed to stdout for workflow capture
    print(topic)
