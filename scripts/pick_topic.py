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

import difflib
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
LOOKBACK = 45

# Similarity threshold for near-duplicate detection (SequenceMatcher.ratio).
# 0.85 is deliberately strict: rejects clear paraphrases while keeping
# genuinely different topics that share common sentence structure.
FUZZY_THRESHOLD = 0.85

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
            "How ravens plan ahead for tomorrow's meal",
            "Why orangutans can learn to use human tools",
            "How rats navigate mazes better than most GPS systems",
            "The elephant that painted self-portraits with a brush",
            "Why bees solve math problems faster than computers",
            "How sea otters teach their pups to crack shellfish",
            "The gorilla who learned 1000 words in sign language",
            "Why cleaner wrasse fish recognize themselves in mirrors",
            "How jays hide thousands of food caches and remember every one",
            "Why squirrels fake-bury food to trick thieves watching them",
            "How macaques in Japan teach their young to wash sweet potatoes",
            "The dog that can distinguish over 200 toys by name alone",
            "Why cuttlefish demonstrate impulse control for delayed rewards",
            "How African grey parrots outperform 5-year-old children in logic tests",
            "Why dolphins create their own game rules and enforce them on others",
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
            "How polar bears stay warm in Arctic blizzards without shelter",
            "Why African elephants can survive weeks between water sources",
            "How snow leopards hunt on cliffs at 18,000 feet altitude",
            "The Himalayan wolf that thrives where oxygen levels are lethal to most",
            "How grizzly bears survive six months of winter without eating",
            "Why reindeer can see ultraviolet light in permanent Arctic darkness",
            "How Australian thorny devil lizards drink through their skin",
            "The painted turtle that survives winter frozen under lake ice",
            "Why emperor penguins can dive 1,800 feet and hold breath 20 minutes",
            "How the Namib desert lion goes months without drinking water",
            "Why mountain goats can stand on ledges two inches wide",
            "How bactrian camels survive minus 40 in winter and 104F in summer",
            "The olm salamander that can survive 10 years without food",
            "Why desert tortoises store a year's water supply inside their bladder",
            "How wolverines cross entire mountain ranges in a single day",
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
            "Why chimpanzees console grieving troop members after a death",
            "How wild horses form lifelong bonds that outlast separation",
            "Why capuchin monkeys reject unequal pay and throw food in protest",
            "How bottlenose dolphins stay with injured companions for days",
            "The gorilla who adopted a stray kitten and grieved when it died",
            "Why bonobos resolve every conflict with physical affection",
            "How African wild dogs vote on when to move camp by sneezing",
            "Why ravens form long-term friendships and hold grudges for years",
            "How mother orangutans grieve and carry dead infants for weeks",
            "Why bats share food with roost-mates who went hungry",
            "How lionesses synchronize pregnancies and raise cubs communally",
            "Why polar bears engage in ritualized play greeting before sparring",
            "How crows bring gifts to humans who regularly feed them",
            "Why elephants return to the bones of deceased family members annually",
            "How sea otters hold hands while sleeping to avoid drifting apart",
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
            "Why wombats produce cube-shaped droppings — the only animal that does",
            "How platypuses detect prey using electrical fields with their bills",
            "Why male seahorses are the ones that carry and birth the young",
            "How the mantis shrimp sees 16 types of color receptors vs. our 3",
            "Why a group of cats is called a clowder and it gets weirder from there",
            "How Tasmanian devils have the strongest bite force relative to body size",
            "Why horned lizards shoot blood from their eyes as a defense",
            "How reindeer eyes change color from gold in summer to blue in winter",
            "Why frilled-neck lizards run on two legs when panicked",
            "How axolotls can regrow their heart and brain, not just limbs",
            "Why shrews must eat three times their body weight every day or die",
            "How the archerfish shoots water jets to knock insects off branches above",
            "Why naked mole rats feel no pain and almost never get cancer",
            "How the pangolin is the only mammal covered entirely in scales",
            "Why echidnas have a four-headed reproductive organ",
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
            "How sperm whales dive deeper than nuclear submarines",
            "Why orcas have been observed teaching each other to hunt",
            "How humpback whales compose new songs that spread across oceans",
            "Why the blue whale's heart is big enough for a human to crawl through",
            "How dolphins use echolocation accurate enough to detect a golf ball 100m away",
            "Why walruses use their tusks as ice picks to climb out of the water",
            "How manatees navigate entire coastlines using only sound detection",
            "Why sea turtles return to the exact beach where they were born decades later",
            "How great white sharks can detect a single drop of blood in an Olympic pool",
            "Why narwhal tusks are actually a tooth grown through their upper lip",
            "How beluga whales can change the shape of their forehead to communicate",
            "Why dugongs were mistaken for mermaids by sailors for centuries",
            "How the mimic octopus impersonates 15 different venomous species on demand",
            "Why the pistol shrimp creates a flash hotter than the sun's surface",
            "How whale falls on the ocean floor sustain entire ecosystems for decades",
        ],
    },
    "big_cats_predators": {
        "prompt_desc": "Big Cats & Apex Predators (lions, tigers, leopards, cheetahs, wolves — hunting behavior, power, strategy)",
        "topics": [
            "How cheetahs use their tail as a rudder at 70 mph",
            "Why lions hunt at night and what their night vision sees",
            "How leopards carry prey heavier than themselves up into trees",
            "Why tigers are solitary but still have strict territorial maps",
            "How snow leopards ambush prey on near-vertical cliff faces",
            "Why a jaguar's bite can pierce a caiman skull through its armor",
            "How wolf packs use relay hunting to exhaust prey over miles",
            "Why cougars can leap 40 feet horizontally in a single bound",
            "How lions coordinate a hunt using only eye contact and positioning",
            "Why clouded leopards have the longest canine teeth of any living cat",
            "How cheetahs recover from a failed hunt in under 30 minutes",
            "Why tigers are the only big cats that actively enjoy water",
            "How African wild dogs have an 85% hunt success rate vs. lions' 25%",
            "Why leopards are the most adaptable big cat and live on every continent",
            "How wolves reintroduced to Yellowstone changed the shape of rivers",
            "Why lions' roar can be heard five miles away and what it signals",
            "How a tiger can take down prey ten times its own body weight",
            "Why cheetahs cannot roar but purr exactly like domestic cats",
            "How ocelots hunt in complete darkness using only their whiskers",
            "Why the Siberian tiger survives minus 40F with no shelter at all",
            "How servals can jump 10 feet straight up to snatch birds mid-flight",
            "Why mountain lions have zero natural predators in North America",
            "How lions recognize each other's roars from miles away in darkness",
            "Why cougars silently follow hikers for miles without ever attacking",
            "How leopards memorize every prey animal's schedule and habits",
        ],
    },
    "reptiles_amphibians": {
        "prompt_desc": "Reptiles & Amphibians (snakes, lizards, frogs, crocodilians — biology, behavior, survival)",
        "topics": [
            "How the Komodo dragon uses bacteria and venom as a dual weapon",
            "Why anacondas can swallow a full-grown deer whole",
            "How chameleons change color using nanocrystals, not pigment",
            "Why the Galapagos marine iguana sneezes salt and dives for algae",
            "How king cobras build and guard nests — the only snake that does",
            "Why poison dart frogs get their toxins entirely from their diet",
            "How crocodiles have been unchanged by evolution for 200 million years",
            "Why the black mamba is the fastest snake on earth and what it hunts",
            "How geckos walk upside down using van der Waals forces, not suction",
            "Why Nile crocodiles store prey underwater and wait weeks to eat",
            "How flying snakes of Southeast Asia glide between trees with no limbs",
            "Why frogs absorb water through their skin instead of drinking it",
            "How the Jackson's chameleon has three horns and uses them in combat",
            "Why the Gila monster chews its venom in rather than injecting it",
            "How alligators create breathing holes in frozen water to survive winter",
            "Why tree frogs can survive being freeze-dried and rehydrate later",
            "How the Inland Taipan snake has enough venom to kill 100 humans in one bite",
            "Why monitor lizards have forked tongues they use like a GPS system",
            "How saltwater crocodiles navigate hundreds of miles of open ocean",
            "Why the thorny dragon lizard can change its entire body color in seconds",
            "How caiman crocodiles herd fish into shallow water cooperatively",
            "Why ball pythons constrict with enough force to stop a heartbeat instantly",
            "How the Jesus lizard runs on water using surface tension",
            "Why rattlesnakes can strike faster than the human eye can follow",
            "How Komodo dragons can reproduce without a male through parthenogenesis",
        ],
    },
}


def _is_too_similar(candidate: str, existing: list[str], threshold: float = FUZZY_THRESHOLD) -> bool:
    """Return True if *candidate* is a near-duplicate of any string in *existing*.

    Uses difflib.SequenceMatcher on lowercased strings so capitalisation
    variants are caught. A ratio >= *threshold* (default 0.85) counts as
    too similar.
    """
    candidate_lower = candidate.lower()
    for topic in existing:
        ratio = difflib.SequenceMatcher(None, candidate_lower, topic.lower()).ratio()
        if ratio >= threshold:
            return True
    return False


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
        print("[pick_topic] _call_groq: GROQ_API_KEY is missing or empty — skipping AI call", file=sys.stderr)
        return None

    try:
        import requests
    except ImportError:
        print("[pick_topic] _call_groq: 'requests' library not installed — skipping AI call", file=sys.stderr)
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
            try:
                data = resp.json()
                raw_content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as parse_err:
                print(
                    f"[pick_topic] _call_groq: Failed to parse Groq response ({parse_err}). "
                    f"Raw body (first 300 chars): {resp.text[:300]}",
                    file=sys.stderr,
                )
                return None
            topic = re.sub(r'^["\'#\*\-\s]+|["\'\s]+$', "", raw_content.strip())
            if topic and len(topic) > 5:
                return topic
            print(
                f"[pick_topic] _call_groq: Groq returned empty/too-short content after stripping "
                f"(raw: {repr(raw_content[:100])})",
                file=sys.stderr,
            )
        else:
            print(
                f"[pick_topic] _call_groq: Groq API returned non-200 status {resp.status_code}. "
                f"Body (first 300 chars): {resp.text[:300]}",
                file=sys.stderr,
            )
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
    if not topic:
        return None
    if _is_too_similar(topic, recent_topics):
        print(
            f"[pick_topic] generate_general_topic_with_ai: AI topic too similar to recent history "
            f"('{topic}') — discarding and falling back to curated list",
            file=sys.stderr,
        )
        return None
    print(f"[pick_topic] Generated dynamic AI topic: {topic}", file=sys.stderr)
    return topic


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
    if not topic:
        print(
            f"[pick_topic] generate_animal_topic_with_ai({category}): _call_groq returned None "
            f"— falling back to curated list",
            file=sys.stderr,
        )
        return None
    if _is_too_similar(topic, recent_topics):
        print(
            f"[pick_topic] generate_animal_topic_with_ai({category}): AI topic too similar to recent history "
            f"('{topic}') — discarding and falling back to curated list",
            file=sys.stderr,
        )
        return None
    print(f"[pick_topic] Generated dynamic AI animal topic ({category}): {topic}", file=sys.stderr)
    return topic


def pick_general_topic(history: list[dict], recent_topics: list[str]) -> str:
    ai_topic = generate_general_topic_with_ai(recent_topics)
    if ai_topic:
        return ai_topic

    available = [t for t in BACKUP_TOPICS if not _is_too_similar(t, recent_topics)]
    if not available:
        # Everything is too similar — avoid only the immediately last topic.
        last_topic = history[-1]["topic"] if history else ""
        available = [t for t in BACKUP_TOPICS if t != last_topic]

    chosen = random.choice(available)
    print(f"[pick_topic] Picked from backup curated list: {chosen}", file=sys.stderr)
    return chosen


def pick_animal_topic(history: list[dict], recent_topics: list[str]) -> str:
    if FORCED_CATEGORY and FORCED_CATEGORY in ANIMAL_CATEGORIES:
        category = FORCED_CATEGORY
    else:
        if FORCED_CATEGORY and FORCED_CATEGORY not in ANIMAL_CATEGORIES:
            print(
                f"[pick_topic] Unknown TOPIC_CATEGORY '{FORCED_CATEGORY}', falling back to weighted random category",
                file=sys.stderr,
            )
        # Weight categories AWAY from recently-used ones.
        # Count how many times each category appears in the recent LOOKBACK entries.
        recent_categories = [
            entry.get("category")
            for entry in history[-LOOKBACK:]
            if entry.get("category") and entry.get("niche") == "animal"
        ]
        category_counts: dict[str, int] = {k: 0 for k in ANIMAL_CATEGORIES}
        for cat in recent_categories:
            if cat in category_counts:
                category_counts[cat] += 1
        max_count = max(category_counts.values(), default=0)
        # weight = (max_count + 1) - own_count → least-used gets highest weight
        weights = [max_count + 1 - category_counts[k] for k in ANIMAL_CATEGORIES]
        category = random.choices(list(ANIMAL_CATEGORIES.keys()), weights=weights, k=1)[0]
        print(
            "[pick_topic] Category weights (recent usage counts): "
            + ", ".join(f"{k}={category_counts[k]}" for k in ANIMAL_CATEGORIES),
            file=sys.stderr,
        )
    print(f"[pick_topic] Animal category selected: {category}", file=sys.stderr)

    ai_topic = generate_animal_topic_with_ai(recent_topics, category)
    if ai_topic:
        return ai_topic

    category_topics = ANIMAL_CATEGORIES[category]["topics"]
    available = [t for t in category_topics if not _is_too_similar(t, recent_topics)]

    if not available:
        # Category exhausted recently — widen search across all animal categories.
        all_animal_topics = [t for cat in ANIMAL_CATEGORIES.values() for t in cat["topics"]]
        available = [t for t in all_animal_topics if not _is_too_similar(t, recent_topics)]
        if not available:
            # Full pool exhausted — avoid only the immediately last topic.
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
            "category": category if NICHE == "animal" else None,
        }
    )
    save_history(history)

    return chosen


if __name__ == "__main__":
    topic = pick_topic()
    print(topic)
