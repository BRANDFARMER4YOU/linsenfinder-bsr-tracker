#!/usr/bin/env python3
"""
BSR Tracker — tägliches Update Script
Scrapet Amazon BSR via Apify, speichert in data.json auf GitHub
Alerts: Preis-Änderungen + Amazon Choice Badge per Telegram
"""
import requests, json, base64, datetime, time, sys, os

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "BRANDFARMER4YOU/linsenfinder-bsr-tracker"
ACTOR_ID = "BG3WDrGdteHgZgbPK"
TELEGRAM_CHAT_ID = "959128749"
TODAY = str(datetime.date.today())

# Telegram Token aus openclaw.json lesen
def get_telegram_token():
    try:
        with open("/Users/felix/.openclaw/openclaw.json") as f:
            d = json.load(f)
        bots = d.get("telegram", {}).get("bots", [])
        if bots:
            return bots[0].get("token", "")
        return d.get("telegram", {}).get("token", "")
    except:
        return ""

def send_telegram(msg):
    token = get_telegram_token()
    if not token:
        print(f"  ⚠️ Kein Telegram Token — Alert nur in Console: {msg[:80]}")
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    )
    print(f"  📱 Telegram Alert gesendet")

CONFIG = {
    "series": {
        "fxcontacts_12m": {"asin": "B0CRBKG853", "domain": "de", "label": "FXCONTACTS 12M", "color": "#00C853"},
        "fxcontacts_day": {"asin": "B0CGJCPS1Q", "domain": "de", "label": "FXCONTACTS Day", "color": "#69F0AE"},
        "aricona_bars":   {"asin": "B08HRWT4HT", "domain": "de", "label": "Aricona (Behind Bars)", "color": "#FF5252"},
        "aricona_vampire":{"asin": "B00H2H5MTI", "domain": "de", "label": "Aricona (Vampire 12M)", "color": "#FF6D00"},
        "designlenses":   {"asin": "B0BQC6R35Y", "domain": "de", "label": "DESIGNLENSES (Day)", "color": "#D500F9"},
        "crazyfun":       {"asin": "B07NGVRYWX", "domain": "de", "label": "Crazy Fun (Red Flower)", "color": "#FF1744"},
    },
    "series_it": {
        "fxcontacts_it":   {"asin": "B09NQGVSPD", "domain": "it", "label": "FXCONTACTS (IT)", "color": "#00C853"},
        "konkurrent_it_1": {"asin": "B0BQC5VM9T", "domain": "it", "label": "Konkurrent IT 1", "color": "#FF5252"},
        "konkurrent_it_2": {"asin": "B0D7CW19DR", "domain": "it", "label": "Konkurrent IT 2", "color": "#FF6D00"},
        "konkurrent_it_3": {"asin": "B07NGVRYWX", "domain": "it", "label": "Konkurrent IT 3", "color": "#D500F9"},
    },
    "series_fr": {
        "fxcontacts_fr":   {"asin": "B09NQGVSPD", "domain": "fr", "label": "FXCONTACTS (FR)", "color": "#00C853"},
        "konkurrent_fr_1": {"asin": "B0CPYG28K3", "domain": "fr", "label": "Konkurrent FR 1", "color": "#FF5252"},
        "konkurrent_fr_2": {"asin": "B0FBX1YXWK", "domain": "fr", "label": "Konkurrent FR 2", "color": "#FF6D00"},
        "konkurrent_fr_3": {"asin": "B0CRZCW2JN", "domain": "fr", "label": "Konkurrent FR 3", "color": "#D500F9"},
    },
    "series_es": {
        "fxcontacts_es":   {"asin": "B09NQGVSPD", "domain": "es", "label": "FXCONTACTS (ES)", "color": "#00C853"},
        "konkurrent_es_1": {"asin": "B0BQC6R35Y", "domain": "es", "label": "Konkurrent ES 1", "color": "#FF5252"},
        "konkurrent_es_2": {"asin": "B0CRZC4226", "domain": "es", "label": "Konkurrent ES 2", "color": "#FF6D00"},
        "konkurrent_es_3": {"asin": "B002Y4I7QE", "domain": "es", "label": "Konkurrent ES 3", "color": "#D500F9"},
    }
}

def scrape_asin(asin, domain="de"):
    url = f"https://www.amazon.{domain}/dp/{asin}"
    print(f"  Scraping {asin} on amazon.{domain}...", flush=True)
    try:
        run = requests.post(
            f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs?waitForFinish=120",
            headers={"Authorization": f"Bearer {APIFY_TOKEN}"},
            json={"categoryOrProductUrls": [{"url": url}], "maxItems": 1, "scrapeProductDetails": True},
            timeout=150
        ).json()
        run_id = run.get("data", {}).get("id")
        if not run_id:
            print(f"    ❌ Kein Run-ID: {run.get('error', 'unbekannt')}")
            return None
        items = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items",
            headers={"Authorization": f"Bearer {APIFY_TOKEN}"}
        ).json()
        if not items:
            print(f"    ❌ Keine Ergebnisse")
            return None
        p = items[0]
        bsr_list = p.get("bestsellerRanks", [])
        bsr, bsr_cat = None, None
        if bsr_list:
            specific = bsr_list[-1] if len(bsr_list) > 1 else bsr_list[0]
            bsr = specific.get("rank")
            bsr_cat = specific.get("category")
        price = p.get("price", {})
        if isinstance(price, dict):
            price = price.get("value")
        title = (p.get("title") or "")[:60]
        is_ac = bool(p.get("isAmazonChoice", False))
        print(f"    ✅ BSR={bsr} Preis={price} AC={'JA ⭐' if is_ac else 'nein'} Title={title[:35]}")
        return {
            "bsr": bsr,
            "bsr_category": bsr_cat,
            "price": price,
            "reviews": p.get("reviewsCount"),
            "rating": p.get("stars"),
            "isAmazonChoice": is_ac,
            "title": title
        }
    except Exception as e:
        print(f"    ❌ Fehler: {e}")
        return None

def get_github_file(path):
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
        headers={"Authorization": f"token {GITHUB_TOKEN}"}
    ).json()
    if "sha" not in r:
        return None, None
    content = base64.b64decode(r["content"].replace("\n","") + "==").decode("utf-8")
    return json.loads(content), r["sha"]

def push_github_file(path, content_str, sha, message):
    encoded = base64.b64encode(content_str.encode()).decode()
    payload = {"message": message, "content": encoded}
    if sha:
        payload["sha"] = sha
    r = requests.put(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
        json=payload
    )
    if r.status_code in (200, 201):
        print(f"  ✅ {path} gepusht")
    else:
        print(f"  ❌ {path} Fehler: {r.status_code} {r.text[:200]}")

def check_alerts(serie_id, label, prev_data, new_point):
    """Prüft auf Preis-Änderungen und Amazon Choice Badge-Wechsel"""
    alerts = []

    if not prev_data:
        return alerts

    prev = prev_data[-1]
    is_fx = serie_id.startswith("fxcontacts")

    # Preis-Änderung (>= 5% oder absolut >= 0.50€)
    old_price = prev.get("price")
    new_price = new_point.get("price")
    if old_price and new_price and old_price != new_price:
        diff = new_price - old_price
        pct = abs(diff) / old_price * 100
        if pct >= 5 or abs(diff) >= 0.50:
            direction = "⬆️ erhöht" if diff > 0 else "⬇️ gesenkt"
            emoji = "🔴" if (not is_fx and diff < 0) else "📊"
            alerts.append(f"{emoji} <b>Preisänderung:</b> {label}\n€{old_price} → €{new_price} ({direction}, {pct:.1f}%)")

    # Amazon Choice Badge — gewonnen oder verloren
    old_ac = prev.get("isAmazonChoice", False)
    new_ac = new_point.get("isAmazonChoice", False)
    if old_ac != new_ac:
        if new_ac:
            emoji = "🏆" if is_fx else "⚠️"
            alerts.append(f"{emoji} <b>Amazon's Choice gewonnen:</b> {label}")
        else:
            emoji = "😬" if is_fx else "✅"
            alerts.append(f"{emoji} <b>Amazon's Choice verloren:</b> {label}")

    return alerts

def main():
    print(f"\n🚀 BSR Update {TODAY}")
    print("=" * 50)

    print("\n📥 Lade data.json von GitHub...")
    data, sha = get_github_file("data.json")
    if not data:
        print("Keine data.json gefunden — erstelle neu")
        data = {}

    for key in ["series", "series_it", "series_fr", "series_es"]:
        if key not in data:
            data[key] = []

    all_alerts = []

    for series_key, series_config in CONFIG.items():
        print(f"\n🌍 {series_key.upper()}")
        existing = {s["id"]: s for s in data.get(series_key, [])}

        for serie_id, cfg in series_config.items():
            if serie_id in existing:
                already = [d for d in existing[serie_id].get("data", []) if d["date"] == TODAY]
                if already:
                    print(f"  ⏭️  {serie_id}: heute bereits eingetragen")
                    continue

            result = scrape_asin(cfg["asin"], cfg["domain"])
            time.sleep(3)

            point = {"date": TODAY}
            if result:
                point.update({
                    "bsr": result["bsr"],
                    "price": result["price"],
                    "reviews": result["reviews"],
                    "rating": result["rating"],
                    "isAmazonChoice": result["isAmazonChoice"],
                })
                if result["title"] and "Konkurrent" in cfg["label"]:
                    cfg["label"] = result["title"][:40]
            else:
                point["bsr"] = None

            if serie_id not in existing:
                existing[serie_id] = {
                    "id": serie_id,
                    "label": cfg["label"],
                    "asin": cfg["asin"],
                    "color": cfg["color"],
                    "data": []
                }

            # Alerts prüfen (vor dem Anhängen)
            prev_data = existing[serie_id].get("data", [])
            alerts = check_alerts(serie_id, existing[serie_id]["label"], prev_data, point)
            all_alerts.extend(alerts)

            existing[serie_id]["data"].append(point)

        data[series_key] = list(existing.values())

    data["updated"] = TODAY

    print(f"\n📤 Pushe data.json nach GitHub...")
    push_github_file("data.json", json.dumps(data, indent=2, ensure_ascii=False), sha, f"BSR update {TODAY}")

    # Zusammenfassung
    print("\n📊 ZUSAMMENFASSUNG")
    print("=" * 50)
    summary_lines = [f"📊 <b>BSR Update {TODAY}</b>\n"]
    for key in ["series", "series_it", "series_fr", "series_es"]:
        flag = {"series": "🇩🇪", "series_it": "🇮🇹", "series_fr": "🇫🇷", "series_es": "🇪🇸"}.get(key, "")
        summary_lines.append(f"\n{flag} <b>{key.upper()}</b>")
        for s in data.get(key, []):
            last = s["data"][-1] if s["data"] else {}
            ac = " ⭐" if last.get("isAmazonChoice") else ""
            line = f"  {s['label'][:30]:30} BSR #{last.get('bsr','n/a')}{ac}"
            print(line)
            summary_lines.append(line)

    # Alerts senden
    if all_alerts:
        print(f"\n🚨 {len(all_alerts)} ALERT(S):")
        alert_msg = f"🚨 <b>BSR Alerts {TODAY}</b>\n\n" + "\n\n".join(all_alerts)
        print(alert_msg)
        send_telegram(alert_msg)
    else:
        print("\n✅ Keine Alerts — alles stabil")

    # Tägliche Zusammenfassung per Telegram
    summary_msg = "\n".join(summary_lines)
    summary_msg += f"\n\n🌐 Dashboard: https://brandfarmer4you.github.io/linsenfinder-bsr-tracker/"
    if all_alerts:
        summary_msg += f"\n\n🚨 {len(all_alerts)} Alert(s) separat gesendet!"
    send_telegram(summary_msg)

    print("\n✅ Fertig!")
    print(f"🌐 Dashboard: https://brandfarmer4you.github.io/linsenfinder-bsr-tracker/")

if __name__ == "__main__":
    main()
