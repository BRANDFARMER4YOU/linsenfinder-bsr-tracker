#!/usr/bin/env python3
"""
Generiert analysis.json (KI-Lageberichte pro Land) aus den aktuellen BSR-Zahlen
in data.json. Läuft täglich nach update_bsr.py als Teil des GitHub Actions Crons.

Nutzt DeepSeek API (DEEPSEEK_API_KEY als Secret/Env-Variable).
"""

import json
import os
import sys
import requests
from datetime import date

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

COUNTRIES = {
    "DE": "Deutschland", "IT": "Italien", "FR": "Frankreich", "ES": "Spanien",
}


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def get_latest_products(data, country_key):
    """Extrahiert die neuesten Produkt-BSR-Werte für ein Land aus data.json.
    series ist eine Liste von {id, label, asin, color, data: [...]} Objekten."""
    series_key = "series" if country_key == "DE" else f"series_{country_key.lower()}"
    series = data.get(series_key, [])
    latest = {}
    for product in series:
        label = product.get("label", product.get("id", "?"))
        points = product.get("data", [])
        # Nur echte BSR-Tracking-Punkte zaehlen: bsr UND price gesetzt.
        # Alte Keyword-Rang-Platzhalter (kleine Zahlen 1-20, price=None,
        # meist vom 01.09.) sind KEINE echten Amazon-BSR-Werte und wuerden
        # die Rangliste verfaelschen -- deshalb hart ausschliessen.
        valid_points = [p for p in points if p.get("bsr") is not None and p.get("price") is not None]
        if not valid_points:
            continue
        newest = max(valid_points, key=lambda p: p.get("date", ""))
        # Bei doppelten Labels (gleicher Produktname mehrfach in der Liste):
        # nur uebernehmen wenn neuer als bereits gespeicherter Wert.
        if label not in latest or newest.get("date", "") > latest[label].get("date", ""):
            latest[label] = newest
    return latest


def build_ranking(latest_products):
    """Sortiert Produkte nach BSR (niedriger = besser), gibt Ranking-Liste zurück."""
    ranked = sorted(latest_products.items(), key=lambda kv: kv[1]["bsr"])
    return ranked


def call_deepseek(prompt):
    if not DEEPSEEK_API_KEY:
        print("WARNUNG: Kein DEEPSEEK_API_KEY gesetzt — überspringe KI-Text-Generierung", file=sys.stderr)
        return None
    try:
        resp = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": 500,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"FEHLER bei DeepSeek-Aufruf: {e}", file=sys.stderr)
        return None


def build_prompt(country_name, flag, ranking, our_products):
    lines = []
    for i, (name, info) in enumerate(ranking, 1):
        marker = " <- UNSER PRODUKT" if name in our_products else ""
        bsr_fmt = f"{info['bsr']:,}".replace(",", ".")
        lines.append(f"{i}. {name}: BSR #{bsr_fmt}{marker}")
    ranking_text = "\n".join(lines)

    our_ranks = [i for i, (name, _) in enumerate(ranking, 1) if name in our_products]
    our_best_rank = min(our_ranks) if our_ranks else None
    our_bsrs = [info["bsr"] for name, info in ranking if name in our_products]
    our_best_bsr = min(our_bsrs) if our_bsrs else None

    return f"""Du schreibst einen kurzen KI-Lagebericht für ein Amazon BSR-Dashboard (Halloween-Kontaktlinsen, Marke FXCONTACTS).

Land: {country_name} {flag}
Aktuelles BSR-Ranking (niedrigerer BSR = bessere Position, {len(ranking)} Produkte gesamt):
{ranking_text}

Unsere beste Position: Rang {our_best_rank} von {len(ranking)}, BSR #{our_best_bsr}

Schreibe einen prägnanten Lagebericht im folgenden Format (auf Deutsch, mit Markdown-Fett):

{flag} **{country_name} — [kurzer Titel zur Lage]**

**BSR-Lage:** [1-2 Sätze, wie stehen wir da, konkrete BSR-Werte nennen]
**Wettbewerb:** [1-2 Sätze zu den wichtigsten Konkurrenten mit Namen und BSR]
**Handlungsempfehlung:** [2-3 Bulletpoints mit •, konkret und umsetzbar]
**Für Mona:** [1 Satz, was Mona operativ tun soll]

WICHTIG: Nutze ausschließlich die oben genannten echten Zahlen. Erfinde keine Werte."""


def main():
    data = load_json("data.json", {})
    today = date.today().isoformat()

    result = {"date": today, "countries": {}}

    for code, name in COUNTRIES.items():
        flag = {"DE": "🇩🇪", "IT": "🇮🇹", "FR": "🇫🇷", "ES": "🇪🇸"}[code]
        latest = get_latest_products(data, code)
        if not latest:
            print(f"WARNUNG: Keine Produktdaten für {code} gefunden", file=sys.stderr)
            continue

        ranking = build_ranking(latest)
        our_products = [name_ for name_, _ in ranking if "FX" in name_.upper()]

        our_ranks = [i for i, (n, _) in enumerate(ranking, 1) if n in our_products]
        our_rank = min(our_ranks) if our_ranks else None
        our_bsrs = [info["bsr"] for n, info in ranking if n in our_products]
        our_bsr = min(our_bsrs) if our_bsrs else None

        prompt = build_prompt(name, flag, ranking, our_products)
        text = call_deepseek(prompt)

        if text is None:
            bsr_fmt = f"{our_bsr:,}".replace(",", ".") if our_bsr else "?"
            text = (
                f"{flag} **{name} — BSR-Update {today}**\n\n"
                f"**BSR-Lage:** Rang {our_rank} von {len(ranking)} mit BSR #{bsr_fmt}.\n"
                f"**Hinweis:** KI-Textgenerierung nicht verfügbar, nur Rohdaten angezeigt."
            )

        result["countries"][code] = {
            "land_name": name,
            "fx_rank": our_rank,
            "fx_bsr": our_bsr,
            "total_products": len(ranking),
            "text": text,
        }
        print(f"✅ {code}: Rang {our_rank}/{len(ranking)}, BSR #{our_bsr}")

    with open("analysis.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n✅ analysis.json aktualisiert (Datum: {today})")


if __name__ == "__main__":
    main()
