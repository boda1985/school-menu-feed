#!/usr/bin/env python3
"""
SchoolCafe -> ICS feed (for Apple Calendar subscription).

Fetches daily menus from SchoolCafe's JSON API for a rolling window and writes
an .ics file with one all-day event per school day.

Setup: paste the menu API URL(s) you captured from Chrome DevTools into MENUS
below (or the MENUS_JSON env var). The script swaps in each date for you.
Standard library only - no pip installs needed.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
# Label -> captured request URL from DevTools (Network tab, the request that
# returns the menu JSON). Add a second entry for breakfast if you want it.
MENUS = {
    "Lunch": "https://webapis.schoolcafe.com/api/CalendarView/GetDailyMenuitemsByGrade?SchoolId=c82a83b4-45d1-4f17-b61d-010c0d8aecd5&ServingDate=10%2F26%2F2026&ServingLine=Main&MealType=Lunch&Grade=EE&PersonId=null",
    "Breakfast": "https://webapis.schoolcafe.com/api/CalendarView/GetDailyMenuitemsByGrade?SchoolId=c82a83b4-45d1-4f17-b61d-010c0d8aecd5&ServingDate=10%2F26%2F2026&ServingLine=Main&MealType=Breakfast&Grade=EE&PersonId=null",
}

CALENDAR_NAME = "Three Creeks Menu"
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "docs/menu.ics")
DAYS_BACK = 7        # keep last week visible
DAYS_AHEAD = 21      # SchoolCafe usually publishes 1-4 weeks out
# Categories shown in the event title (rest go in the notes).
TITLE_CATEGORIES = ("ENTREE", "ENTREES", "MAIN", "MAIN ENTREE")
# Categories left out of the event entirely (noise on a calendar).
SKIP_CATEGORIES = ("CONDIMENTS", "MILK")
# ---------------------------------------------------------------------------

if os.environ.get("MENUS_JSON"):
    MENUS = json.loads(os.environ["MENUS_JSON"])

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (menu-to-calendar script)",
}


def url_for_date(template: str, d: date) -> str:
    """Replace the ServingDate query param, keeping its original format."""
    parts = urllib.parse.urlsplit(template)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    new_query, found = [], False
    for k, v in query:
        if k.lower() == "servingdate":
            found = True
            if re.match(r"^\d{4}-\d{2}-\d{2}", v):
                v = d.isoformat()
            else:  # default SchoolCafe style MM/DD/YYYY
                v = d.strftime("%m/%d/%Y")
        new_query.append((k, v))
    if not found:
        sys.exit("Captured URL has no ServingDate parameter - recheck DevTools.")
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(new_query)))


def fetch(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def item_name(item) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("MenuItemDescription", "ItemName", "Name", "Description", "name"):
            if item.get(key):
                return str(item[key]).strip()
    return ""


def parse_menu(data) -> dict:
    """Return {category: [items]} from the common SchoolCafe response shapes."""
    menu = {}
    if isinstance(data, dict):
        for cat, items in data.items():
            if isinstance(items, list):
                names = [n for n in (item_name(i) for i in items) if n]
                if names and str(cat).strip().upper() not in SKIP_CATEGORIES:
                    menu[str(cat).strip().upper()] = names
    elif isinstance(data, list):  # flat list with a category field
        for i in data:
            if not isinstance(i, dict):
                continue
            cat = str(i.get("Category") or i.get("Station") or "MENU").strip().upper()
            n = item_name(i)
            if n:
                menu.setdefault(cat, []).append(n)
    # de-dupe while keeping order
    return {c: list(dict.fromkeys(v)) for c, v in menu.items()}


def ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line: str) -> str:
    """RFC 5545 line folding at 75 octets."""
    out, buf = [], line.encode("utf-8")
    while len(buf) > 75:
        cut = 75
        while (buf[cut] & 0xC0) == 0x80:  # don't split a UTF-8 char
            cut -= 1
        out.append(buf[:cut].decode("utf-8"))
        buf = b" " + buf[cut:]
    out.append(buf.decode("utf-8"))
    return "\r\n".join(out)


def build_event(d: date, label: str, menu: dict, stamp: str) -> list:
    title_items = []
    for c in TITLE_CATEGORIES:
        title_items += menu.get(c, [])
    if not title_items:  # fall back to first category
        title_items = next(iter(menu.values()))
    summary = f"{label}: " + " / ".join(title_items[:3])
    notes = "\n".join(f"{c.title()}: {', '.join(items)}" for c, items in menu.items())
    nxt = d + timedelta(days=1)
    return [
        "BEGIN:VEVENT",
        f"UID:{d.isoformat()}-{label.lower()}@schoolcafe-menu",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{nxt.strftime('%Y%m%d')}",
        f"SUMMARY:{ics_escape(summary)}",
        f"DESCRIPTION:{ics_escape(notes)}",
        "TRANSP:TRANSPARENT",  # shows as free, won't block time
        "END:VEVENT",
    ]


def main():
    if any("PASTE_CAPTURED" in u for u in MENUS.values()):
        sys.exit("Paste your captured SchoolCafe URL into MENUS first.")

    today = date.today()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//schoolcafe-to-ics//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CALENDAR_NAME}",
        "X-WR-TIMEZONE:America/Denver",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    count, errors = 0, 0
    for offset in range(-DAYS_BACK, DAYS_AHEAD + 1):
        d = today + timedelta(days=offset)
        if d.weekday() >= 5:  # skip weekends
            continue
        for label, template in MENUS.items():
            try:
                menu = parse_menu(fetch(url_for_date(template, d)))
            except Exception as e:  # keep going on a bad day
                errors += 1
                print(f"WARN {d} {label}: {e}", file=sys.stderr)
                continue
            if menu:  # empty = no school / not published yet
                lines += build_event(d, label, menu, stamp)
                count += 1
    lines.append("END:VCALENDAR")

    if count == 0:
        # Don't overwrite a good feed with an empty one if the API broke.
        sys.exit(f"No menu days found ({errors} errors) - leaving existing feed untouched.")

    os.makedirs(os.path.dirname(OUTPUT_PATH) or ".", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(fold(l) for l in lines) + "\r\n")
    print(f"Wrote {count} events to {OUTPUT_PATH} ({errors} fetch errors)")


if __name__ == "__main__":
    main()
