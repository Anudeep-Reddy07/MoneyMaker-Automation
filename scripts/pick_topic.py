#!/usr/bin/env python3
"""Pick or generate a non-repeating video topic.

Two niches are supported, selected by the TOPIC_NICHE environment variable:

  TOPIC_NICHE unset / "general" (default, used by auto-video.yml):
      Original behaviour — AI/Tech, Finance, Productivity, Science niches.

  TOPIC_NICHE=animal (used by animal-video.yml):
      Picks from 5 animal categories (animal_intelligence,
      animal_survival_extreme, animal_emotions_social, weird_animal_facts,
      ocean_deep_sea). TOPIC_CATEGORY can force one specific category;
      if empty, a category is chosen at random ("weighted auto-pick").

Mode 1 (AI Dynamic - Default):
    Calls the Groq LLM to brainstorm a fresh, viral, trending Short topic,
    injecting past history so the AI never repeats an idea.

Mode 2 (Curated Fallback):
    If the LLM is unreachable or GROQ_API_KEY is not set, picks randomly
    from a curated topic library matching the active niche/category.

The chosen topic is printed to stdout and recorded in topic_history.json.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from datetime import datetime, timezone

HISTORY_FILE = os.environ.get(
    "TOPIC_HISTORY_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "topic_history.json"),
)

# Lookback window for history checks
LOOKBACK = 20

NICHE = os.environ.get("TOPIC_NICHE", "general").strip().lower()
FORCED_CATEGORY = os.environ.get("TOPIC_CATEGORY", "").strip()

# ---------------------------------------------------------------------------
# GENERAL niche: curated backup topics (~60 total), original behaviour.
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

GENERAL_NICHE_PROMPT_INTRO = (
    "Niches to choose from (pick 1):\n"
    "- AI & Future Technology\n"
    "- Smart Money, Investing & Wealth Psychology\n"
    "- High-Performance Habits & Productivity Hacks\n"
    "- Mindblowing Science & Human Body Secrets\n\n"
)

# ---------------------------------------------------------------------------
# ANIMAL niche: 5 categories, each with its own curated backup topics and
# its own AI-prompt description.
# ---------------------------------------------------------------------------
ANIMAL_CATEGORIES: dict[str, dict] = {
    "animal_intelligence": {
        "prompt_desc": "Animal Intelligence & Problem-Solving (tool use, memory, planning, communication)",
        "topics": [
            "The octopus that can open childproof jars",
            "Why crows can recognize human faces for years",
            "How elephants pass a mirror self-recognition test",
            "The parrot that understood zero as a concept",
            "How dolphins call each other by unique names",
            "Why pigs are smarter than most dogs",
            "The chimp that beats humans at memory games",
            "How border collies learn over 1000 words",
            "Why octopuses have nine brains, not one",
            "The crow that solved an 8-step puzzle for food",
        ],
    },
    "animal_survival_extreme": {
        "prompt_desc": "Animal Survival in Extreme Environments (deserts, deep cold, deep sea, disaster resilience)",
        "topics": [
            "The frog that survives being frozen solid",
            "How camels survive weeks without water",
            "The fish that lives in boiling hot springs",
            "How tardigrades survive the vacuum of space",
            "The bird that flies nonstop for 11 days straight",
            "How Arctic foxes survive minus 50 degrees",
            "The shrimp that lives in scalding deep-sea vents",
            "Why cockroaches can survive a nuclear blast radius",
            "How desert beetles harvest water from thin air",
            "The worm that survives being cut into pieces",
        ],
    },
    "animal_emotions_social": {
        "prompt_desc": "Animal Emotions & Social Bonds (grief, friendship, empathy, family structure)",
        "topics": [
            "Do elephants really mourn their dead",
            "The orca who carried her dead calf for weeks",
            "Why dogs get jealous just like humans do",
            "How wolf packs are actually led by mothers",
            "The rats that free trapped friends before eating",
            "Why elephants comfort each other with their trunks",
            "How magpies hold what looks like a funeral",
            "The unlikely friendship between a lion and a dog",
            "Why geese mate for life and grieve when separated",
            "How meerkats babysit pups that are not their own",
        ],
    },
    "weird_animal_facts": {
        "prompt_desc": "Weird & Bizarre Animal Facts (shock value, strange biology, surprising trivia)",
        "topics": [
            "The shrimp that punches faster than a bullet",
            "Why flamingos are born gray, not pink",
            "The fish with a see-through head",
            "How sea cucumbers breathe through their anus",
            "Why a group of flamingos is called a flamboyance",
            "The snail that can sleep for three years",
            "How starfish can regrow an entire new body",
            "The spider that can walk on water",
            "Why sloths only poop once a week",
            "The jellyfish that is biologically immortal",
        ],
    },
    "ocean_deep_sea": {
        "prompt_desc": "Deep Sea & Ocean Mysteries (bioluminescence, pressure, undiscovered creatures)",
        "topics": [
            "What actually lives at the bottom of the Mariana Trench",
            "The anglerfish that lures prey with its own light",
            "Why the deep ocean is darker than outer space",
            "How giant squids evolved eyes the size of basketballs",
            "The fish that survives crushing deep-sea pressure",
            "Why most of the ocean floor remains unmapped",
            "The vampire squid that is neither vampire nor squid",
            "How bioluminescent creatures create their own light",
            "The deep-sea fish with a transparent head dome",
            "Why scientists find new ocean species every year",
        ],
    },
}


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


def _call_groq(prompt: str) -> str | None:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        import requests
    except ImportError:
        return None

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
            if topic and len(topic) > 5:
                return topic
        else:
            print(f"[pick_topic] Groq API returned status {resp.status_code}", file=sys.stderr)
    except Exception as exc:
        print(f"[pick_topic] AI topic generation failed ({exc})", file=sys.stderr)

    return None


def generate_general_topic_with_ai(recent_topics: list[str]) -> str | None:
    recent_str = "\n- ".join(recent_topics[-15:]) if recent_topics else "None"
    prompt = (
        "You are an elite YouTube Shorts growth strategist. Brainstorm 1 viral, high-CTR Short video topic.\n"
        f"{GENERAL_NICHE_PROMPT_INTRO}"
        f"DO NOT repeat or closely mirror any of these recently used topics:\n- {recent_str}\n\n"
        "Guidelines:\n"
        "1. Max 7-10 words. Punchy, curiosity-inducing, broad enough for stock video footage to match.\n"
        "2. Return ONLY the topic title text. No quotes, no markdown, no emojis, no commentary."
    )
    topic = _call_groq(prompt)
    if topic and topic not in recent_topics:
        print(f"[pick_topic] Generated dynamic AI topic: {topic}", file=sys.stderr)
        return topic
    return None


def generate_animal_topic_with_ai(recent_topics: list[str], category: str) -> str | None:
    desc = ANIMAL_CATEGORIES[category]["prompt_desc"]
    recent_str = "\n- ".join(recent_topics[-15:]) if recent_topics else "None"
    prompt = (
        "You are an elite YouTube Shorts growth strategist specializing in animal content.\n"
        f"Brainstorm 1 viral, high-CTR Short video topic strictly in this category:\n{desc}\n\n"
        f"DO NOT repeat or closely mirror any of these recently used topics:\n- {recent_str}\n\n"
        "Guidelines:\n"
        "1. Max 7-10 words. Punchy, curiosity-inducing, name a specific real animal or species where possible.\n"
        "2. Must be factually plausible — no invented/fictional animal claims.\n"
        "3. Return ONLY the topic title text. No quotes, no markdown, no emojis, no commentary."
    )
    topic = _call_groq(prompt)
    if topic and topic not in recent_topics:
        print(f"[pick_topic] Generated dynamic AI animal topic ({category}): {topic}", file=sys.stderr)
        return topic
    return None


def pick_general_topic(history: list[dict], recent_topics: list[str]) -> str:
    ai_topic = generate_general_topic_with_ai(recent_topics)
    if ai_topic:
        return ai_topic

    recent_set = set(recent_topics)
    available = [t for t in BACKUP_TOPICS if t not in recent_set]
    if not available:
        last_topic = history[-1]["topic"] if history else ""
        available = [t for t in BACKUP_TOPICS if t != last_topic]

    chosen = random.choice(available)
    print(f"[pick_topic] Picked from backup curated list: {chosen}", file=sys.stderr)
    return chosen


def pick_animal_topic(history: list[dict], recent_topics: list[str]) -> str:
    category = FORCED_CATEGORY if FORCED_CATEGORY in ANIMAL_CATEGORIES else random.choice(
        list(ANIMAL_CATEGORIES.keys())
    )
    if FORCED_CATEGORY and FORCED_CATEGORY not in ANIMAL_CATEGORIES:
        print(
            f"[pick_topic] Unknown TOPIC_CATEGORY '{FORCED_CATEGORY}', falling back to weighted random category",
            file=sys.stderr,
        )
    print(f"[pick_topic] Animal category selected: {category}", file=sys.stderr)

    ai_topic = generate_animal_topic_with_ai(recent_topics, category)
    if ai_topic:
        return ai_topic

    recent_set = set(recent_topics)
    category_topics = ANIMAL_CATEGORIES[category]["topics"]
    available = [t for t in category_topics if t not in recent_set]

    if not available:
        # Category exhausted recently — widen search across all animal categories.
        all_animal_topics = [t for cat in ANIMAL_CATEGORIES.values() for t in cat["topics"]]
        available = [t for t in all_animal_topics if t not in recent_set]
        if not available:
            last_topic = history[-1]["topic"] if history else ""
            available = [t for t in all_animal_topics if t != last_topic]

    chosen = random.choice(available)
    print(f"[pick_topic] Picked from backup animal list ({category}): {chosen}", file=sys.stderr)
    return chosen


def pick_topic() -> str:
    """Select or generate a non-repeating topic for the active niche."""
    history = load_history()
    recent_topics = [entry["topic"] for entry in history[-LOOKBACK:] if "topic" in entry]

    manual_override = os.environ.get("MANUAL_TOPIC_OVERRIDE", "").strip()
    if manual_override:
        chosen = manual_override
    elif NICHE == "animal":
        chosen = pick_animal_topic(history, recent_topics)
    else:
        chosen = pick_general_topic(history, recent_topics)

    history.append(
        {
            "topic": chosen,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "niche": NICHE,
        }
    )
    save_history(history)

    return chosen


if __name__ == "__main__":
    topic = pick_topic()
    print(topic)
