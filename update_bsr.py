#!/usr/bin/env python3
"""
BSR Tracker Updater — FXCONTACTS / BRANDFARMER4YOU
Fetches BSR from Amazon.de/it/fr/es for multiple ASINs and updates data.json via GitHub API.

Appends one data point per series per day (idempotent — duplicate runs on the
same day update the existing entry instead of inserting a second one).

Usage:
    GITHUB_TOKEN=ghp_xxx python3 update_bsr.py

Env vars:
    GITHUB_TOKEN   – required, GitHub PAT with repo write access
    GITHUB_REPO    – optional (default: BRANDFARMER4YOU/linsenfinder-bsr-tracker)
    DRY_RUN        – optional, set to 1 to skip GitHub push
"""

import os
import re
import json
import base64
import time
import random
import logging
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ─────────────────────────── Config ───────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "BRANDFARMER4YOU/linsenfinder-bsr-tracker")
DRY_RUN      = os.environ.get("DRY_RUN", "0") == "1"
DATA_FILE    = "data.json"
TODAY        = date.today().isoformat()

# ── DE (amazon.de) – series key: "series" ──
ASINS_DE = [
    ("fxcontacts_12m",  "B0CRBKG853"),
    ("fxcontacts_day",  "B0CGJCPS1Q"),
    ("konkurrent_1",    "B08HRWT4HT"),
    ("konkurrent_2",    "B00H2H5MTI"),
    ("konkurrent_3",    "B0BQC6R35Y"),
    ("konkurrent_4",    "B07NGVRYWX"),
]

# ── IT (amazon.it) – series key: "series_it" ──
ASINS_IT = [
    ("fxcontacts_day",  "B0CGJCPS1Q"),
    ("konkurrent_1",    "B0BQC5VM9T"),
    ("konkurrent_2",    "B0D7CW19DR"),
    ("konkurrent_3",    "B07NGVRYWX"),
]

# ── FR (amazon.fr) – series key: "series_fr" ──
ASINS_FR = [
    ("fxcontacts_day",  "B0CGJCPS1Q"),
    ("konkurrent_1",    "B0CPYG28K3"),
    ("konkurrent_2",    "B0FBX1YXWK"),
    ("konkurrent_3",    "B0CRZCW2JN"),
]

# ── ES (amazon.es) – series key: "series_es" ──
ASINS_ES = [
    ("fxcontacts_day",  "B0CGJCPS1Q"),
    ("konkurrent_1",    "B0BQC6R35Y"),
    ("konkurrent_2",    "B0CRZC4226"),
    ("konkurrent_3",    "B002Y4I7QE"),
]

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

LANG_HEADERS = {
    "de": "de-DE,de;q=0.9,en;q=0.8",
    "it": "it-IT,it;q=0.9,en;q=0.8",
    "fr": "fr-FR,fr;q=0.9,en;q=0.8",
    "es": "es-ES,es;q=0.9,en;q=0.8",
}

# BSR row keywords per marketplace
BSR_KEYWORDS = [
    "Amazon Bestseller-Rang",            # DE
    "Posizione nella classifica",        # IT
    "Classement des meilleures ventes",  # FR
    "Clasificación en los más vendidos", # ES
    "Best Sellers Rank",                 # EN fallback
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bsr-updater")

# ─────────────────────────── BSR Fetcher ───────────────────────────

def extract_bsr(soup: BeautifulSoup, text: str) -> Optional[int]:
    """Extract top-level BSR from Amazon product page (any EU locale)."""
    for el in soup.select("tr, li, li.a-list-item"):
        t = el.get_text(" ", strip=True)
        if any(kw.lower() in t.lower() for kw in BSR_KEYWORDS):
            # Patterns: nº2.230 / n. 6.839 / #4.290 / 4 290 / Nr. 1.234
            nums = re.findall(
                r'(?:n[º°]\s*|n\.\s*|Nr\.\s*|#\s*)([\d](?:[\d\s\.,]{1,10}[\d])|\d{1,7})', t
            )
            for num_str in nums:
                cleaned = re.sub(r'[\s\.,]', '', num_str)
                if cleaned.isdigit():
                    val = int(cleaned)
                    if 10 <= val <= 9_999_999:
                        return val
    # JSON fallback
    m = re.search(r'"salesRank"\s*:\s*(\d+)', text)
    if m:
        return int(m.group(1))
    return None


def fetch_bsr(asin: str, domain: str = "de", retries: int = 3) -> Optional[int]:
    """Fetch BSR from Amazon.<domain> product page."""
    url = f"https://www.amazon.{domain}/dp/{asin}"
    headers = {**BASE_HEADERS, "Accept-Language": LANG_HEADERS.get(domain, "en-US")}

    for attempt in range(1, retries + 1):
        try:
            time.sleep(random.uniform(3.0, 7.0))  # polite delay
            resp = requests.get(url, headers=headers, timeout=25, allow_redirects=True)

            if resp.status_code == 404:
                log.info(f"[{domain}/{asin}] 404 – not listed in this marketplace, skipping")
                return None

            if resp.status_code == 503 or "captcha" in resp.url.lower():
                log.warning(f"[{domain}/{asin}] Attempt {attempt}: CAPTCHA/503, waiting…")
                time.sleep(30 * attempt)
                continue

            if resp.status_code != 200:
                log.warning(f"[{domain}/{asin}] Attempt {attempt}: HTTP {resp.status_code}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            bsr = extract_bsr(soup, resp.text)

            if bsr is not None:
                log.info(f"[{domain}/{asin}] BSR = {bsr:,}")
                return bsr
            else:
                log.warning(f"[{domain}/{asin}] Attempt {attempt}: BSR not found in page")

        except Exception as e:
            log.error(f"[{domain}/{asin}] Attempt {attempt}: {e}")
            time.sleep(10)

    log.error(f"[{domain}/{asin}] All {retries} attempts failed, skipping")
    return None


# ─────────────────────────── GitHub API ───────────────────────────

API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"

def gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

def get_current_data() -> tuple[dict, str]:
    """Returns (data_dict, sha) from GitHub."""
    resp = requests.get(API, headers=gh_headers())
    resp.raise_for_status()
    info = resp.json()
    sha = info["sha"]
    content = base64.b64decode(info["content"]).decode("utf-8")
    return json.loads(content), sha

def push_data(data: dict, sha: str, message: str = None):
    """Push updated data.json back to GitHub."""
    if DRY_RUN:
        log.info("DRY_RUN: skipping GitHub push")
        log.info(json.dumps(data, indent=2, ensure_ascii=False))
        return
    msg = message or f"BSR update {TODAY}"
    encoded = base64.b64encode(json.dumps(data, indent=2, ensure_ascii=False).encode()).decode()
    payload = {"message": msg, "content": encoded, "sha": sha}
    resp = requests.put(API, headers=gh_headers(), json=payload)
    resp.raise_for_status()
    log.info(f"✅ data.json updated on GitHub (commit: {resp.json()['commit']['sha'][:8]})")


# ─────────────────────────── Helpers ───────────────────────────

def update_series(series_list: list, bsr_results: dict, label_prefix: str = ""):
    """
    Append or update today's BSR entry for each series.
    Idempotent: if today's entry already exists, updates the value.
    """
    updated = 0
    for series in series_list:
        sid = series["id"]
        if sid not in bsr_results:
            log.warning(f"[{label_prefix}{sid}] No new BSR — keeping existing data")
            continue

        new_bsr = bsr_results[sid]
        series.setdefault("data", [])
        existing = next((e for e in series["data"] if e["date"] == TODAY), None)

        if existing is not None:
            if existing["bsr"] != new_bsr:
                log.info(f"[{label_prefix}{sid}] Updating {TODAY}: #{existing['bsr']:,} → #{new_bsr:,}")
                existing["bsr"] = new_bsr
            else:
                log.info(f"[{label_prefix}{sid}] Already up-to-date (#{new_bsr:,})")
        else:
            series["data"].append({"date": TODAY, "bsr": new_bsr})
            log.info(f"[{label_prefix}{sid}] Appended {TODAY}: #{new_bsr:,}")

        updated += 1
    return updated


# ─────────────────────────── Main ───────────────────────────

def main():
    if not GITHUB_TOKEN and not DRY_RUN:
        raise ValueError("GITHUB_TOKEN env var is required (or set DRY_RUN=1)")

    log.info(f"=== BSR Update — {TODAY} ===")

    # ── Fetch DE ──
    log.info("--- Fetching DE ---")
    bsr_de: dict[str, int] = {}
    for sid, asin in ASINS_DE:
        bsr = fetch_bsr(asin, domain="de")
        if bsr is not None:
            bsr_de[sid] = bsr

    # ── Fetch IT ──
    log.info("--- Fetching IT ---")
    bsr_it: dict[str, int] = {}
    for sid, asin in ASINS_IT:
        bsr = fetch_bsr(asin, domain="it")
        if bsr is not None:
            bsr_it[sid] = bsr

    # ── Fetch FR ──
    log.info("--- Fetching FR ---")
    bsr_fr: dict[str, int] = {}
    for sid, asin in ASINS_FR:
        bsr = fetch_bsr(asin, domain="fr")
        if bsr is not None:
            bsr_fr[sid] = bsr

    # ── Fetch ES ──
    log.info("--- Fetching ES ---")
    bsr_es: dict[str, int] = {}
    for sid, asin in ASINS_ES:
        bsr = fetch_bsr(asin, domain="es")
        if bsr is not None:
            bsr_es[sid] = bsr

    total_fetched = len(bsr_de) + len(bsr_it) + len(bsr_fr) + len(bsr_es)
    if not total_fetched:
        log.error("No BSR data fetched at all — aborting")
        return

    # ── Load current data.json ──
    if DRY_RUN:
        log.info("DRY_RUN: using stub data")
        data = {"updated": TODAY, "series": [], "series_it": [], "series_fr": [], "series_es": []}
        sha = "dummy"
    else:
        data, sha = get_current_data()

    # ── Update each country's series ──
    updated_de = update_series(data.get("series", []), bsr_de, "DE/")
    updated_it = update_series(data.get("series_it", []), bsr_it, "IT/")
    updated_fr = update_series(data.get("series_fr", []), bsr_fr, "FR/")
    updated_es = update_series(data.get("series_es", []), bsr_es, "ES/")

    data["updated"] = TODAY

    # ── Push ──
    push_data(data, sha)

    log.info(
        f"=== Done. Updated DE:{updated_de} IT:{updated_it} FR:{updated_fr} ES:{updated_es} ==="
    )


if __name__ == "__main__":
    main()
