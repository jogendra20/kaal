"""
staleness_check.py
Cross-checks each 'fresh' quarterly-results announcement against an LLM
for semantic staleness (catches cases keyword-matching misses: reworded
corrigendum language, re-submissions, duplicate filings under different
phrasing) that filter_results.py's keyword filter can't catch alone.

Uses Mistral as primary, Groq as fallback -- same pattern as NEXUS.
Auto-loads API keys from a .env file (searches current dir and parents).

Usage:
    python staleness_check.py fresh_results.csv
"""

import csv
import os
import sys
import time
import requests


def load_dotenv(start_dir="."):
    """
    Minimal .env loader -- no external dependency needed.
    Searches current dir, then walks up parent dirs looking for .env.
    """
    path = os.path.abspath(start_dir)
    for _ in range(5):  # search up to 5 levels up
        candidate = os.path.join(path, ".env")
        if os.path.isfile(candidate):
            with open(candidate) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    os.environ.setdefault(key, val)
            print(f"[env] loaded {candidate}")
            return True
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    print("[env] no .env file found in current or parent directories")
    return False


load_dotenv()

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a filter for Indian stock exchange (NSE) corporate announcements. "
    "Given a SUBJECT and DETAILS text, decide if this is a FRESH, first-time "
    "quarterly financial results filing, or STALE (a corrigendum, amendment, "
    "resubmission, duplicate, clarification, or reference to results already "
    "filed earlier). Reply with ONLY one word: FRESH or STALE. No explanation."
)


def call_mistral(subject: str, details: str):
    if not MISTRAL_API_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"SUBJECT: {subject}\nDETAILS: {details}"},
        ],
        "max_tokens": 5,
        "temperature": 0,
    }
    try:
        r = requests.post(MISTRAL_URL, headers=headers, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip().upper()
    except Exception as e:
        print(f"  [mistral error: {e}]")
        return None


def call_groq(subject: str, details: str):
    if not GROQ_API_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"SUBJECT: {subject}\nDETAILS: {details}"},
        ],
        "max_tokens": 5,
        "temperature": 0,
    }
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip().upper()
    except Exception as e:
        print(f"  [groq error: {e}]")
        return None


def classify(subject: str, details: str):
    result = call_mistral(subject, details)
    source = "mistral"
    if not result or ("FRESH" not in result and "STALE" not in result):
        result = call_groq(subject, details)
        source = "groq"
    if not result:
        return "UNKNOWN", "none"
    verdict = "FRESH" if "FRESH" in result else "STALE"
    return verdict, source


def run(csv_path: str):
    if not MISTRAL_API_KEY and not GROQ_API_KEY:
        print("ERROR: no keys found. Check your .env has MISTRAL_API_KEY and/or GROQ_API_KEY.")
        sys.exit(1)

    fresh_count = 0
    stale_count = 0
    fresh_rows = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Classifying {len(rows)} announcements via LLM staleness check...\n")

    for i, row in enumerate(rows, 1):
        symbol = row["symbol"]
        subject = row["subject"]
        details = row["details"]

        verdict, source = classify(subject, details)
        print(f"[{i}/{len(rows)}] {symbol:15s} {verdict} (via {source})")

        if verdict == "FRESH":
            fresh_count += 1
            fresh_rows.append(row)
        else:
            stale_count += 1

        time.sleep(0.3)

    print(f"\n--- Summary ---")
    print(f"Fresh: {fresh_count}  |  Stale: {stale_count}")

    out_path = "llm_confirmed_fresh.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "company", "subject", "details"])
        writer.writeheader()
        for r in fresh_rows:
            writer.writerow(r)
    print(f"Saved LLM-confirmed fresh list to {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python staleness_check.py fresh_results.csv")
        sys.exit(1)
    run(sys.argv[1])
