#!/usr/bin/env python3
"""
BSR Tracker Updater — FXCONTACTS / BRANDFARMER4YOU
Fetches BSR from Amazon.de for 6 ASINs and updates data.json via GitHub API.

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

ASINS = [
    ("fxcontacts_12m",  "B0CRBKG853"),
    ("fxcontacts_day",  "B0CGJCPS1Q"),
    ("konkurrent_1",    "B08HRWT4HT"),
    ("konkurrent_2",    "B00H2H5MTI"),
    ("konkurrent_3",    "B0BQC6R35Y"),
    ("konkurrent_4",    "B07NGVRYWX"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bsr-updater")

# ─────────────────────────── BSR Fetcher ───────────────────────────

def fetch_bsr(asin: str, retries: int = 3) -> Optional[int]:
    """Fetch BSR (Drogerie & Körperpflege) from Amazon.de product page."""
    url = f"https://www.amazon.de/dp/{asin}"
    for attempt in range(1, retries + 1):
        try:
            time.sleep(random.uniform(3.0, 7.0))  # polite delay
            resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
            if resp.status_code == 503 or "captcha" in resp.url.lower():
                log.warning(f"[{asin}] Attempt {attempt}: CAPTCHA/503, waiting…")
                time.sleep(30 * attempt)
                continue
            if resp.status_code != 200:
                log.warning(f"[{asin}] Attempt {attempt}: HTTP {resp.status_code}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Method 1: detailBulletsWrapper (newer layout)
            for li in soup.select("li, tr"):
                text = li.get_text(" ", strip=True)
                if "Amazon Bestseller-Rang" in text or "Best Sellers Rank" in text:
                    # First number = top-level BSR
                    nums = re.findall(r"Nr\.\s*([\d\.]+)|#([\d\.,]+)", text)
                    if nums:
                        raw = nums[0][0] or nums[0][1]
                        bsr = int(re.sub(r"[^\d]", "", raw))
                        log.info(f"[{asin}] BSR = {bsr:,} (actual URL: {resp.url})")
                        return bsr

            # Method 2: data-csa-c-content-id or salesRank in page source
            m = re.search(r'"salesRank"\s*:\s*(\d+)', resp.text)
            if m:
                bsr = int(m.group(1))
                log.info(f"[{asin}] BSR (JSON) = {bsr:,}")
                return bsr

            log.warning(f"[{asin}] Attempt {attempt}: BSR not found in page")

        except Exception as e:
            log.error(f"[{asin}] Attempt {attempt}: {e}")
            time.sleep(10)

    log.error(f"[{asin}] All {retries} attempts failed, skipping")
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


# ─────────────────────────── Main ───────────────────────────

def main():
    if not GITHUB_TOKEN and not DRY_RUN:
        raise ValueError("GITHUB_TOKEN env var is required (or set DRY_RUN=1)")

    log.info(f"=== BSR Update — {TODAY} ===")

    # 1. Fetch all BSR values
    bsr_results: dict[str, int] = {}
    for series_id, asin in ASINS:
        bsr = fetch_bsr(asin)
        if bsr is not None:
            bsr_results[series_id] = bsr

    if not bsr_results:
        log.error("No BSR data fetched at all — aborting")
        return

    # 2. Load current data.json from GitHub
    if DRY_RUN:
        log.info("DRY_RUN: using dummy data structure")
        data = {"updated": TODAY, "series": [
            {"id": sid, "label": sid, "asin": asin, "color": "#888", "data": []}
            for sid, asin in ASINS
        ]}
        sha = "dummy"
    else:
        data, sha = get_current_data()

    # 3. Add new data points
    updated_count = 0
    for series in data["series"]:
        sid = series["id"]
        if sid not in bsr_results:
            log.warning(f"[{sid}] No new BSR — keeping existing data")
            continue
        new_bsr = bsr_results[sid]
        # Avoid duplicate entries for same date
        existing_dates = {d["date"] for d in series.get("data", [])}
        if TODAY in existing_dates:
            log.info(f"[{sid}] Already has entry for {TODAY}, updating value")
            for entry in series["data"]:
                if entry["date"] == TODAY:
                    entry["bsr"] = new_bsr
        else:
            series.setdefault("data", []).append({"date": TODAY, "bsr": new_bsr})
        updated_count += 1
        log.info(f"[{sid}] #{new_bsr:,}")

    data["updated"] = TODAY

    # 4. Push back
    push_data(data, sha)
    log.info(f"=== Done. Updated {updated_count}/{len(ASINS)} series ===")


if __name__ == "__main__":
    main()
