#!/usr/bin/env python3
"""
One-time script to scrape glove data from poedb.tw.
Run: python scrape_data.py
"""
import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://poe2db.tw/us"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
DATA_DIR = "data"
GLOVE_TYPES = ["str", "dex", "int", "str_dex", "str_int", "dex_int"]


def fetch(path: str) -> str:
    """Fetch a poedb page with a small delay to avoid hammering the server."""
    time.sleep(1.0)
    url = f"{BASE_URL}/{path}"
    print(f"  GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def clean_stat_html(html_str: str) -> str:
    """Convert HTML-formatted stat text to plain text."""
    soup = BeautifulSoup(html_str, "html.parser")
    # Replace ndash spans with " to "
    for span in soup.find_all("span", class_="ndash"):
        span.replace_with("-")
    text = soup.get_text()
    return " ".join(text.split())


def _find_section_title(html: str, modsview_pos: int) -> str:
    """
    Search backward from a ModsView(...) call position in raw HTML to find
    the nearest section heading text (card-header, h5, h6, or similar).
    Returns the section name or empty string if not found.
    """
    # Look at the 2000 chars before the ModsView call
    window = html[max(0, modsview_pos - 2000): modsview_pos]
    soup = BeautifulSoup(window, "html.parser")

    # Try card-header first (poedb uses Bootstrap cards)
    headers = soup.find_all(class_="card-header")
    if headers:
        return headers[-1].get_text(strip=True)

    # Try h5, h6 headings
    for tag in ("h5", "h6", "h4", "h3"):
        headings = soup.find_all(tag)
        if headings:
            return headings[-1].get_text(strip=True)

    # Try any element whose text contains "Modifiers"
    for el in soup.find_all(True):
        text = el.get_text(strip=True)
        if "Modifiers" in text and len(text) < 80:
            return text

    return ""


def extract_modsview(html: str) -> list:
    """
    Extract modifier dicts from the ModsView({...}) call in the page.
    The JSON has separate keys per category: 'normal', 'desecrated', 'essence', etc.
    Tags each mod with '_section' = category name.
    """
    all_mods = []
    marker = "new ModsView("
    start = html.find(marker)
    if start == -1:
        return all_mods

    j_start = start + len(marker)
    depth = 0
    end = j_start

    for end in range(j_start, len(html)):
        c = html[end]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break

    raw = html[j_start : end + 1]
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"    [warn] ModsView JSON parse failed: {e}")
        return all_mods

    # Extract mods from each category, tagging with section name
    categories_of_interest = [
        "normal", "desecrated", "corrupted", "essence",
        "socketable", "bonded", "veiled",
    ]
    for category in categories_of_interest:
        mods = data.get(category)
        if not isinstance(mods, list) or not mods:
            continue
        for m in mods:
            if isinstance(m, dict):
                m["_section"] = category
        all_mods.extend(mods)

    return all_mods


def scrape_modifiers(glove_type: str) -> list:
    """Scrape all modifiers for a given glove type."""
    html = fetch(f"Gloves_{glove_type}")
    raw_mods = extract_modsview(html)

    if not raw_mods:
        print(f"    [warn] No ModsView data found for Gloves_{glove_type}")
        # Fallback: try to parse HTML table directly
        return _fallback_parse_mods(html, glove_type)

    results = []
    for m in raw_mods:
        if not isinstance(m, dict):
            continue
        stat_html = m.get("str", "") or m.get("stat", "")
        if not stat_html:
            continue

        gen_type_id = str(m.get("ModGenerationTypeID", "0"))
        mod_type = "Prefix" if gen_type_id == "1" else "Suffix"

        level_req = 0
        try:
            level_req = int(m.get("Level", 0))
        except (ValueError, TypeError):
            pass

        section = m.get("_section", "")
        is_desecrated = "desecrat" in section.lower()

        results.append({
            "code": m.get("Code", ""),
            "name": m.get("Name", ""),
            "stat": clean_stat_html(stat_html),
            "type": mod_type,
            "level": level_req,
            "tier": m.get("Tier", ""),
            "drop_chance": m.get("DropChance", 0),
            "family": m.get("ModFamilyList", []),
            "glove_type": glove_type,
            "section": section,
            "desecrated": is_desecrated,
        })

    return results


def _fallback_parse_mods(html: str, glove_type: str) -> list:
    """Fallback: try to extract mods from rendered HTML tables."""
    soup = BeautifulSoup(html, "lxml")
    results = []

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        stat_text = cells[-1].get_text(strip=True) if cells else ""
        if stat_text:
            results.append({
                "code": "",
                "name": "",
                "stat": stat_text,
                "type": "Unknown",
                "level": 0,
                "tier": "",
                "drop_chance": 0,
                "family": [],
                "glove_type": glove_type,
            })

    return results


def scrape_base_gloves(html: str) -> list:
    """Parse base glove types from the #GlovesItem tab pane."""
    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()

    # Items are inside the #GlovesItem tab pane specifically
    pane = soup.find("div", id="GlovesItem")
    if not pane:
        print("    [warn] #GlovesItem tab pane not found")
        return items

    for col in pane.find_all("div", class_="col"):
        flex = col.find("div", class_="d-flex")
        if not flex:
            continue

        # Name is in the link inside .flex-grow-1, not the image link in .flex-shrink-0
        details = flex.find("div", class_="flex-grow-1")
        if not details:
            continue

        link = details.find("a", class_="whiteitem")
        if not link:
            continue

        name = link.get_text(strip=True)
        if not name or name in seen:
            continue
        seen.add(name)

        href = link.get("href", "")

        # Image URL from the .flex-shrink-0 thumbnail
        image_url = ""
        thumb_div = flex.find("div", class_="flex-shrink-0")
        if thumb_div:
            img = thumb_div.find("img")
            if img:
                image_url = img.get("src", "") or img.get("data-src", "")
            else:
                # Sometimes it's a background-image style
                a_tag = thumb_div.find("a")
                if a_tag:
                    style = a_tag.get("style", "")
                    m = re.search(r"url\(['\"]?([^'\")\s]+)['\"]?\)", style)
                    if m:
                        image_url = m.group(1)

        # Properties (Armour, Evasion, Energy Shield)
        props = {}
        for prop_div in details.find_all("div", class_="property"):
            kw = prop_div.find("a", class_="KeywordPopups")
            val = prop_div.find("span", class_="colourDefault")
            if kw and val:
                props[kw.get_text(strip=True)] = val.get_text(strip=True)

        # Requirements
        reqs = {}
        req_div = details.find("div", class_="requirements")
        if req_div:
            req_text = req_div.get_text()
            for pattern, key in [
                (r"Level\s+(\d+)", "level"),
                (r"(\d+)\s+Str", "str"),
                (r"(\d+)\s+Dex", "dex"),
                (r"(\d+)\s+Int", "int"),
            ]:
                m = re.search(pattern, req_text)
                if m:
                    reqs[key] = int(m.group(1))

        # Determine glove type from defence stats
        has_armour = "Armour" in props
        has_evasion = "Evasion" in props
        has_es = "Energy Shield" in props

        if has_armour and has_evasion and has_es:
            glove_type = "str_dex_int"
        elif has_armour and has_evasion:
            glove_type = "str_dex"
        elif has_armour and has_es:
            glove_type = "str_int"
        elif has_evasion and has_es:
            glove_type = "dex_int"
        elif has_armour:
            glove_type = "str"
        elif has_evasion:
            glove_type = "dex"
        elif has_es:
            glove_type = "int"
        else:
            # Fallback: infer from stat requirements
            has_str = "str" in reqs
            has_dex = "dex" in reqs
            has_int = "int" in reqs
            if has_str and has_dex:
                glove_type = "str_dex"
            elif has_str and has_int:
                glove_type = "str_int"
            elif has_dex and has_int:
                glove_type = "dex_int"
            elif has_str:
                glove_type = "str"
            elif has_dex:
                glove_type = "dex"
            elif has_int:
                glove_type = "int"
            else:
                glove_type = "universal"

        items.append({
            "name": name,
            "href": href,
            "type": glove_type,
            "image": image_url,
            "properties": props,
            "requirements": reqs,
        })

    return items


def scrape_unique_gloves(html: str) -> list:
    """Parse unique gloves from the #GlovesUnique tab pane.

    Structure: <a class="uniqueitem">
                 <span class="uniqueName">Name</span>
                 <span class="uniqueTypeLine">Base Type</span>
               </a>
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()

    pane = soup.find("div", id="GlovesUnique")
    if not pane:
        print("    [warn] #GlovesUnique tab pane not found")
        return items

    for col in pane.find_all("div", class_="col"):
        flex = col.find("div", class_="d-flex")
        if not flex:
            continue

        details = flex.find("div", class_="flex-grow-1")
        if not details:
            continue

        # Find the link with unique name/type spans
        link = details.find("a", class_="uniqueitem")
        if not link:
            continue

        name_span = link.find("span", class_="uniqueName")
        type_span = link.find("span", class_="uniqueTypeLine")

        name = name_span.get_text(strip=True) if name_span else link.get_text(strip=True)
        base_type = type_span.get_text(strip=True) if type_span else ""

        if not name or name in seen:
            continue
        seen.add(name)

        items.append({
            "name": name,
            "href": link.get("href", ""),
            "base_type": base_type,
        })

    return items


def main():
    os.makedirs(f"{DATA_DIR}/modifiers", exist_ok=True)

    # --- Base + Unique gloves ---
    print("Fetching Gloves page...")
    gloves_html = fetch("Gloves")

    print("Parsing base gloves...")
    base_gloves = scrape_base_gloves(gloves_html)
    with open(f"{DATA_DIR}/gloves_base.json", "w", encoding="utf-8") as f:
        json.dump(base_gloves, f, indent=2, ensure_ascii=False)
    print(f"  Saved {len(base_gloves)} base gloves to data/gloves_base.json")

    print("Parsing unique gloves...")
    unique_gloves = scrape_unique_gloves(gloves_html)
    with open(f"{DATA_DIR}/gloves_unique.json", "w", encoding="utf-8") as f:
        json.dump(unique_gloves, f, indent=2, ensure_ascii=False)
    print(f"  Saved {len(unique_gloves)} unique gloves to data/gloves_unique.json")

    # --- Modifiers per glove type ---
    for glove_type in GLOVE_TYPES:
        print(f"\nScraping modifiers: Gloves({glove_type})...")
        try:
            mods = scrape_modifiers(glove_type)
            path = f"{DATA_DIR}/modifiers/{glove_type}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(mods, f, indent=2, ensure_ascii=False)
            print(f"  Saved {len(mods)} modifiers to {path}")
        except Exception as e:
            print(f"  ERROR scraping Gloves_{glove_type}: {e}")

    print("\nDone! All data saved to data/")


if __name__ == "__main__":
    main()
