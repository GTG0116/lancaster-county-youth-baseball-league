#!/usr/bin/env python3
"""Download LCYBL official PDF sheets and update generated/static data.

The repository currently contains a static export rather than the original app
source. This script therefore does two things:

1. Downloads and parses every official standings/scores PDF URL already bundled
   into the static site.
2. When parsing succeeds for every required document, rewrites the minified
   schedule and standings chunks so the deployed static pages use the latest
   extracted data.

The parser intentionally fails closed with --require-complete: if the league
changes the PDF layout enough that data cannot be read, the workflow stops
instead of publishing blank or partial standings/schedules.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]


def find_app_chunk(route: str) -> Path:
    """Locate the (single) Next.js page chunk for an app route.

    The filename carries a content hash (``page-<hash>.js``). Because this
    script rewrites that hash on every data change to bust browser/CDN caches
    (see ``cache_bust_chunk``), the chunk must be discovered by glob rather than
    referenced by a fixed name that would go stale after the first sync.
    """
    matches = sorted((ROOT / "_next/static/chunks/app" / route).glob("page-*.js"))
    if not matches:
        raise RuntimeError(f"No page-*.js chunk found for the {route!r} route.")
    if len(matches) > 1:
        raise RuntimeError(
            f"Expected exactly one page chunk for {route!r}; found {len(matches)}: "
            + ", ".join(p.name for p in matches)
        )
    return matches[0]


SCHEDULE_CHUNK = find_app_chunk("schedule")
STANDINGS_CHUNK = find_app_chunk("standings")
GENERATED_DIR = ROOT / "data/generated"
GENERATED_JSON = GENERATED_DIR / "lcybl-official-data.json"
USER_AGENT = "LCYBL-static-data-sync/1.0 (+https://github.com/)"

# The league publishes its standings/scores PDFs through a GoDaddy Website
# Builder site. Crucially, when a sheet is re-uploaded the blobby URL gets a new
# hash suffix (e.g. ``14uSec1Scores.XLS-1311b95.pdf`` becomes
# ``...-59f9d20.pdf``). The URLs that were baked into this repo's static export
# therefore freeze on the day of the build and the workflow keeps re-parsing
# stale PDFs. To stay current we re-discover the live PDF URLs from the league
# site on every run (see ``discover_official_documents``).
LEAGUE_BASE = "https://lancoyouthbaseball.org"
LEAGUE_SCORES_INDEX = "/schedule-%2F-scores"
LEAGUE_STANDINGS_INDEX = "/standings-1"


@dataclass(frozen=True)
class OfficialDocument:
    division: str
    section: int
    standings_url: str | None
    scores_url: str

    @property
    def key(self) -> str:
        return f"{self.division}-section-{self.section}"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_if_changed(path: Path, text: str) -> bool:
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def extract_official_documents() -> list[OfficialDocument]:
    """Read the official PDF URLs from the bundled static chunks.

    The same module is duplicated in schedule and standings chunks. We parse the
    first available copy so URL updates in the built site become the source of
    truth for this automation.
    """
    for chunk in (SCHEDULE_CHUNK, STANDINGS_CHUNK):
        if not chunk.exists():
            continue
        js = read_text(chunk)
        base_match = re.search(r'let\s+([a-zA-Z_$][\w$]*)="(https://img1\.wsimg\.com/[^"]+)"', js)
        if not base_match:
            continue
        base_var, base_url = base_match.groups()
        item_re = re.compile(
            r'\{division:"(?P<division>[^"]+)",section:(?P<section>\d+),'
            r'standingsUrl:(?P<standings>void 0|""\.concat\(' + re.escape(base_var) + r',"(?P<stand_path>[^"]+)"\)),'
            r'scoresUrl:""\.concat\(' + re.escape(base_var) + r',"(?P<scores_path>[^"]+)"\)\}'
        )
        docs: list[OfficialDocument] = []
        for match in item_re.finditer(js):
            standings_url = None
            if match.group("standings") != "void 0":
                standings_url = urllib.parse.urljoin(base_url + "/", match.group("stand_path").lstrip("/"))
            docs.append(
                OfficialDocument(
                    division=match.group("division"),
                    section=int(match.group("section")),
                    standings_url=standings_url,
                    scores_url=urllib.parse.urljoin(base_url + "/", match.group("scores_path").lstrip("/")),
                )
            )
        if docs:
            return docs
    raise RuntimeError("Could not find official LCYBL document URLs in the static chunks.")


def download(url: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - trusted league URLs from bundled site
        return response.read(), dict(response.headers.items())


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - trusted league site
        return response.read().decode("utf-8", "replace")


_SECTION_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_SLUG_RE = re.compile(r"(\d+)u-section-(one|two|three|four|five|six|\d+)", re.IGNORECASE)


def _section_from_slug(slug: str) -> tuple[str, int] | None:
    match = _SLUG_RE.search(slug)
    if not match:
        return None
    division = f"{int(match.group(1))}U"
    token = match.group(2).lower()
    section = _SECTION_WORDS.get(token) or (int(token) if token.isdigit() else None)
    return (division, section) if section else None


def _first_pdf_url(html: str, name_keyword: str) -> str | None:
    """Return the first wsimg PDF URL on a page whose filename matches keyword.

    Section pages can also link unrelated PDFs (e.g. tournament flyers in a
    sidebar), so we require the league's naming convention ("Scores"/"Standing")
    to avoid grabbing the wrong document.
    """
    for raw in re.findall(r"(?:https:)?//img1\.wsimg\.com/blobby/go/[^\"'\\ ]+?\.pdf", html, re.IGNORECASE):
        if name_keyword.lower() in raw.lower():
            return ("https:" + raw) if raw.startswith("//") else raw
    return None


def discover_official_documents() -> list[OfficialDocument]:
    """Discover the *current* scores/standings PDF URLs from the live league site.

    The league's pages link to per-section subpages (e.g. ``/14u-section-one-scores``)
    that embed the latest blobby PDF URL. We crawl the two index pages, follow
    each section subpage, and read the fresh URL — so re-uploaded sheets (which
    change their URL hash) are always picked up.
    """
    scores: dict[tuple[str, int], str] = {}
    standings: dict[tuple[str, int], str] = {}
    for index_path, kind, keyword, bucket in (
        (LEAGUE_SCORES_INDEX, "scores", "Scores", scores),
        (LEAGUE_STANDINGS_INDEX, "standings", "Standing", standings),
    ):
        index_html = fetch_text(LEAGUE_BASE + index_path)
        slugs = sorted(set(re.findall(r'href="(/[a-z0-9%-]*' + kind + r'[a-z0-9%-]*)"', index_html, re.IGNORECASE)))
        for slug in slugs:
            section = _section_from_slug(slug)
            if not section:
                continue
            url = _first_pdf_url(fetch_text(LEAGUE_BASE + slug), keyword)
            if url:
                bucket[section] = url

    docs: list[OfficialDocument] = []
    for key in sorted(scores):
        division, section = key
        docs.append(
            OfficialDocument(
                division=division,
                section=section,
                standings_url=standings.get(key),
                scores_url=scores[key],
            )
        )
    return docs


def resolve_official_documents() -> list[OfficialDocument]:
    """Prefer freshly discovered URLs; fall back to baked URLs per missing section.

    Live discovery is authoritative because it always reflects the league's
    latest uploads. The baked-in URLs are only used to backfill a section that
    discovery could not find (e.g. a transient site error), so a section is never
    silently dropped from the published data.
    """
    try:
        discovered = discover_official_documents()
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"WARNING: live URL discovery failed ({exc}); using baked URLs.", file=sys.stderr)
        discovered = []

    try:
        baked = extract_official_documents()
    except RuntimeError:
        baked = []

    merged: dict[tuple[str, int], OfficialDocument] = {(d.division, d.section): d for d in baked}
    for doc in discovered:
        merged[(doc.division, doc.section)] = doc  # discovered wins

    if not merged:
        raise RuntimeError("Could not determine any official LCYBL document URLs.")
    return [merged[key] for key in sorted(merged)]


def extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - exercised in CI if deps missing
        raise RuntimeError("Install parser dependencies with `python -m pip install -r requirements-lcybl-sync.txt`.") from exc

    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        extracted = page.extract_text() or ""
        pages.append(f"\n--- page {index} ---\n{extracted}")
    return "\n".join(pages)


def normalized_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\u00a0", " ").splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def parse_date(value: str) -> str | None:
    value = value.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y"):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_number(value: str) -> int | float | None:
    value = value.strip().replace(",", "")
    if re.fullmatch(r"\d+", value):
        return int(value)
    if re.fullmatch(r"\d+\.\d+", value):
        return float(value)
    return None


def split_columns(line: str) -> list[str]:
    # pypdf often collapses whitespace, so prefer large gaps when present and
    # otherwise fall back to a conservative single-space split later.
    columns = [col.strip() for col in re.split(r"\s{2,}|\t+", line) if col.strip()]
    return columns if len(columns) > 1 else [line.strip()]


def schedule_status(home_score: int | None, away_score: int | None, date: str) -> str:
    if home_score is not None and away_score is not None:
        return "final"
    return "scheduled"


def parse_schedule_text(text: str, doc: OfficialDocument) -> list[dict[str, Any]]:
    """Best-effort parser for the league score/schedule PDF tables.

    Handles two formats depending on the PDF layout pypdf produces:

    Legacy (m/d/yyyy, single-space):
      5/26/2026 6:00 PM Home Team 7 Away Team 6 Field Name

    Current (d-Mon-yy, multi-space column separators):
      13-Apr-26 Mon 1225 6:00PM   Wenger Field   E-Town Bruins   8 Donegal Indians   12 Z

    In the current format the remainder after the time is separated by 2+ spaces
    into: Location | Home | HomeScore+Visitor | VisitorScore+Status. A missing
    status code (trailing space only) means the game has not yet been played.

    If the PDF layout changes, --require-complete prevents bad partial output
    from being published.
    """
    games: list[dict[str, Any]] = []
    date_re = re.compile(
        r"(?P<date>"
        r"\b\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})\b"
        r"|\b\d{4}-\d{2}-\d{2}\b"
        r"|\b\d{1,2}-[A-Za-z]{3}-\d{2,4}\b"
        r")"
    )
    time_re = re.compile(r"(?P<time>\b\d{1,2}:\d{2}\s*(?:AM|PM)\b)", re.IGNORECASE)

    for raw in text.replace(" ", " ").splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line:
            continue
        if any(skip in line.lower() for skip in ("date time", "date day", "lancaster county", "section", "scores")):
            continue
        date_match = date_re.search(line)
        time_match = time_re.search(line)
        if not date_match or not time_match:
            continue
        date = parse_date(date_match.group("date"))
        if not date:
            continue
        time = re.sub(r"\s+", " ", time_match.group("time").upper())

        # Use the raw (un-collapsed) line for column splitting so that multi-space
        # separators produced by pypdf for tabular PDFs are preserved.
        raw_time_match = time_re.search(raw)
        raw_end = raw_time_match.end() if raw_time_match else time_match.end()
        remainder = raw[raw_end:].strip(" -|")
        if not remainder:
            continue

        columns = split_columns(remainder)
        home: str = ""
        away: str = ""
        field: str = ""
        home_score: int | float | None = None
        away_score: int | float | None = None

        if len(columns) >= 4 and parse_number(columns[1]) is None:
            # Current format: Location | Home | HomeScore+Visitor | VisitorScore+Status
            field = columns[0].strip()
            home = columns[1].strip()
            sv_match = re.match(r"^(\S+)\s+(.+)$", columns[2].strip())
            if sv_match:
                home_score = parse_number(sv_match.group(1))
                away = sv_match.group(2).strip()
            else:
                away = columns[2].strip()
            vs_match = re.match(r"^(\S+)(?:\s+(\S+))?", columns[3].strip())
            if vs_match:
                away_score = parse_number(vs_match.group(1))
                status_code = (vs_match.group(2) or "").strip()
                # No status code → game not yet played; suppress the 0-placeholder scores
                if not status_code:
                    home_score = away_score = None
        elif len(columns) >= 5:
            # Legacy format: Home | HomeScore | Away | AwayScore | Field...
            home, maybe_home_score, away, maybe_away_score = columns[:4]
            home_score = parse_number(maybe_home_score)
            away_score = parse_number(maybe_away_score)
            if isinstance(home_score, int) and isinstance(away_score, int):
                field = " ".join(columns[4:])
            else:
                home, away = columns[0], columns[1]
                home_score = away_score = None
                field = " ".join(columns[2:])
        else:
            # Fallback for collapsed rows: locate numeric scores, if any, and
            # split around them. This is intentionally conservative.
            score_matches = list(re.finditer(r"(?<!\S)\d{1,2}(?!\S)", remainder))
            if len(score_matches) >= 2:
                first, second = score_matches[0], score_matches[1]
                home = remainder[: first.start()].strip(" -|")
                home_score = int(first.group())
                away = remainder[first.end() : second.start()].strip(" -|")
                away_score = int(second.group())
                field = remainder[second.end() :].strip(" -|")
            else:
                parts = remainder.split(" at ", 1)
                if len(parts) != 2:
                    continue
                away, rest = parts
                rest_parts = rest.rsplit(" ", 1)
                home = rest_parts[0].strip()
                field = rest_parts[1].strip() if len(rest_parts) > 1 else ""
                home_score = away_score = None

        if not home or not away:
            continue
        game = {
            "id": f"{doc.division}-{doc.section}-{len(games)}",
            "date": date,
            "time": time,
            "division": doc.division,
            "section": f"Section {doc.section}",
            "home": home,
            "away": away,
            "field": field,
            "status": schedule_status(home_score if isinstance(home_score, int) else None, away_score if isinstance(away_score, int) else None, date),
        }
        if isinstance(home_score, int):
            game["homeScore"] = home_score
        if isinstance(away_score, int):
            game["awayScore"] = away_score
        games.append(game)

    # De-duplicate rows that may appear in page headers/continued tables.
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for game in games:
        key = (game["date"], game["time"], game["home"], game["away"], game.get("homeScore"), game.get("awayScore"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(game)
    return unique


_CLEAN_TEAM_RE = re.compile(r"^D\d*\s+|\d+\s+")
_STATS_HEADER_RE = re.compile(r"\bwins?\b.*\blosses?\b.*\bties?\b", re.IGNORECASE)
# Seeding/playoff headers begin with "Seed" or "Team" before the column names.
# Regular division headers begin with the bracket/division name (e.g. "American").
_SEEDING_HEADER_RE = re.compile(r"^(?:seed|team)\b", re.IGNORECASE)


def _clean_team_name(raw: str) -> str:
    """Strip seeding prefix (D, D1, 2, 3, …) and LCYBL org suffix."""
    name = re.sub(r"\s+", " ", raw).strip(" -|")
    name = _CLEAN_TEAM_RE.sub("", name).strip()
    name = re.sub(r"\s+LCYBL\s*$", "", name, flags=re.IGNORECASE).strip()
    return name


def make_standing_row(match: re.Match[str], rank: int) -> dict[str, Any]:
    row = {
        "team": _clean_team_name(match.group("team")),
        "wins": int(match.group("wins")),
        "losses": int(match.group("losses")),
        "ties": int(match.group("ties")),
        "pct": float(match.group("pct")),
        "points": int(match.group("points")),
        "runsAllowed": int(match.group("ra")),
        "gamesRemaining": int(match.group("gr")),
        "champion": rank == 0,
    }
    return row


def parse_standings_text(text: str, doc: OfficialDocument, headers: dict[str, str]) -> dict[str, Any] | None:
    row_re = re.compile(
        r"^(?P<team>.+?)\s+"
        r"(?P<wins>\d+)\s+(?P<losses>\d+)\s+(?P<ties>\d+)\s+"
        r"(?P<pct>\d+(?:\.\d+)?)%?\s+"
        r"(?P<points>\d+)\s+(?P<ra>\d+)\s+(?P<gr>\d+)\s*$"
    )
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] = {"rows": []}
    in_seeding_section = False

    for line in normalized_lines(text):
        lower = line.lower()
        if not line or lower.startswith("--- page"):
            continue

        # ── column-header lines (Wins/Losses/Ties without being a data row) ──
        if _STATS_HEADER_RE.search(line) and not row_re.match(line):
            if _SEEDING_HEADER_RE.match(line):
                # "Team Wins…" or "Seed Team Wins…" → playoff-seeding repeat table.
                in_seeding_section = True
            else:
                # Per-division header like "American Wins…", "National Wins…", or
                # just "Wins…" (no bracket name).  Extract the text before "Wins".
                name = re.split(r"\bWins?\b", line, flags=re.IGNORECASE)[0].strip(" -|")
                if name:
                    if current["rows"]:
                        groups.append(current)
                    current = {"name": name, "rows": []}
            continue

        if in_seeding_section:
            continue

        if "division" in lower and not row_re.match(line):
            # Strip trailing column headers that pypdf sometimes concatenates.
            name = re.split(r"\bWins?\b", line, flags=re.IGNORECASE)[0]
            name = re.sub(r"\s+", " ", name).strip(" -|")
            if current["rows"]:
                groups.append(current)
            current = {"name": name, "rows": []}
            continue

        match = row_re.match(line)
        if match:
            current["rows"].append(make_standing_row(match, len(current["rows"])))
            continue

        # ── standalone bracket-name line (e.g. "Brown") with no stats ──
        # Short all-letter lines that don't contain digits are likely bracket labels.
        if re.match(r"^[A-Za-z][A-Za-z\s\-']{2,24}$", line) and not any(c.isdigit() for c in line):
            if current["rows"]:
                groups.append(current)
            current = {"name": line.strip(" -|"), "rows": []}

    if current["rows"]:
        groups.append(current)
    if not groups:
        return None

    last_modified = headers.get("Last-Modified") or headers.get("last-modified")
    if last_modified:
        updated = last_modified
    else:
        updated = dt.date.today().strftime("%-m/%-d/%Y") if sys.platform != "win32" else dt.date.today().strftime("%#m/%#d/%Y")

    # Drop placeholder group names that are just column-header noise.
    for group in groups:
        if group.get("name", "").lower().startswith(("standings", "team", "seed")):
            group.pop("name", None)

    # Deduplicate rows within each group by team name (seeding table may slip
    # through if a section's PDF omits the second header line).
    for group in groups:
        seen_teams: set[str] = set()
        unique_rows: list[dict[str, Any]] = []
        for row in group["rows"]:
            if row["team"] not in seen_teams:
                seen_teams.add(row["team"])
                unique_rows.append(row)
        group["rows"] = unique_rows

    return {
        "division": doc.division,
        "section": doc.section,
        "label": f"{doc.division} · Section {doc.section}",
        "updated": updated,
        "note": "Parsed automatically from the league's official standings PDF.",
        "groups": groups,
    }


def serialize_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def serialize_js(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def cache_bust_chunk(chunk: Path) -> Path:
    """Rename a patched chunk to a fresh content-hash filename and update refs.

    The deployed static pages reference each app chunk by its hashed filename in
    exactly two places: the route's ``index.html`` (script tag + preloads) and
    ``index.txt`` (the RSC flight payload). When we rewrite a chunk's contents in
    place but keep the same filename, browsers and CDNs that already cached the
    old file by URL keep serving stale standings/scores. Renaming the file to a
    hash of its new contents changes the URL, forcing a fresh fetch the moment
    the workflow publishes. Returns the (possibly unchanged) chunk path.
    """
    content = chunk.read_bytes()
    new_name = f"page-{hashlib.sha256(content).hexdigest()[:16]}.js"
    if new_name == chunk.name:
        return chunk
    route = chunk.parent.name  # e.g. "schedule" or "standings"
    old_name = chunk.name
    new_path = chunk.with_name(new_name)
    chunk.rename(new_path)
    for ref in (ROOT / route / "index.html", ROOT / route / "index.txt"):
        if not ref.exists():
            continue
        text = ref.read_text(encoding="utf-8")
        if old_name in text:
            ref.write_text(text.replace(old_name, new_name), encoding="utf-8")
    return new_path


def patch_between(path: Path, start_marker: str, end_marker: str, replacement: str) -> bool:
    text = read_text(path)
    start = text.find(start_marker)
    if start == -1:
        raise RuntimeError(f"Could not find start marker in {path}: {start_marker}")
    end = text.find(end_marker, start)
    if end == -1:
        raise RuntimeError(f"Could not find end marker in {path}: {end_marker}")
    patched = text[:start] + replacement + text[end:]
    return write_if_changed(path, patched)


# Maximum number of completed games to embed per section. Older games are
# dropped so the JS bundle stays small and the schedule page renders quickly.
MAX_RESULTS_PER_SECTION = 40


def trim_schedule_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep all scheduled games and the most recent MAX_RESULTS_PER_SECTION
    completed games per section, then re-sort chronologically."""
    from collections import defaultdict

    by_section: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for game in games:
        by_section[(game["division"], game["section"])].append(game)

    trimmed: list[dict[str, Any]] = []
    for section_games in by_section.values():
        final = sorted(
            (g for g in section_games if g["status"] == "final"),
            key=lambda g: (g["date"], g["time"]),
            reverse=True,
        )[:MAX_RESULTS_PER_SECTION]
        scheduled = [g for g in section_games if g["status"] != "final"]
        trimmed.extend(final)
        trimmed.extend(scheduled)

    return sorted(trimmed, key=lambda g: (g["date"], g["time"], g["division"], g["section"], g["home"]))


def patch_static_chunks(games: list[dict[str, Any]], standings: list[dict[str, Any]]) -> list[Path]:
    changed: list[Path] = []
    if games:
        display_games = trim_schedule_games(games)
        # v is the static array of section-tab descriptors used by function x().
        # It must be included here because patch_between replaces everything
        # between the start marker and ;function x(), which originally contained
        # both the S games array and the v tabs array.
        # v and k must be included here because patch_between replaces everything
        # between the start marker and ;function x(), which originally contained
        # the S games array, the v section-tab descriptors, and the var k=l(6933)
        # module require — all of which are needed by function x().
        V_TABS = 'v=[{division:"10U",section:1},{division:"10U",section:2},{division:"10U",section:3},{division:"12U",section:1},{division:"12U",section:2},{division:"12U",section:3},{division:"14U",section:1},{division:"14U",section:2},{division:"14U",section:3}]'
        replacement = f"let S={serialize_js(display_games)},{V_TABS};var k=l(6933)"
        # The original build uses `let p="6:00 PM",S=`; after the first patch
        # `p` is gone and the marker becomes `let S=`.
        schedule_start = 'let p="6:00 PM",S=' if 'let p="6:00 PM",S=' in read_text(SCHEDULE_CHUNK) else "let S="
        if patch_between(SCHEDULE_CHUNK, schedule_start, ';function x()', replacement):
            changed.append(SCHEDULE_CHUNK)
        # Default the section tabs to the first section (index 0) instead of
        # whatever hard-coded index was baked into the original build.
        text = read_text(SCHEDULE_CHUNK)
        patched = re.sub(r"useState\)\(\d+\),l=v\[e\]", "useState)(0),l=v[e]", text, count=1)
        if write_if_changed(SCHEDULE_CHUNK, patched) and SCHEDULE_CHUNK not in changed:
            changed.append(SCHEDULE_CHUNK)
    if standings:
        replacement = f"let c={serialize_js(standings)}"
        if patch_between(STANDINGS_CHUNK, "let c=", ";function l(e)", replacement):
            changed.append(STANDINGS_CHUNK)

    # Bust caches for every chunk whose contents actually changed by renaming it
    # to a fresh content hash and updating the pages that reference it. Without
    # this, returning visitors keep the previously cached (stale) chunk URL.
    busted: list[Path] = []
    for chunk in dict.fromkeys(changed):  # preserve order, de-duplicate
        busted.append(cache_bust_chunk(chunk))
    return busted


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync(args: argparse.Namespace) -> int:
    docs = resolve_official_documents()
    all_games: list[dict[str, Any]] = []
    all_standings: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="lcybl-pdf-") as temp_dir:
        temp = Path(temp_dir)
        for doc in docs:
            for kind, url in (("scores", doc.scores_url), ("standings", doc.standings_url)):
                if not url:
                    continue
                try:
                    pdf_bytes, headers = download(url)
                    text = extract_pdf_text(pdf_bytes)
                except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
                    failures.append(f"{doc.key} {kind}: download/extract failed: {exc}")
                    continue

                text_path = temp / f"{doc.key}-{kind}.txt"
                text_path.write_text(text, encoding="utf-8")
                parsed: Any
                if kind == "scores":
                    parsed = parse_schedule_text(text, doc)
                    if not parsed:
                        failures.append(f"{doc.key} scores: no games parsed")
                    all_games.extend(parsed)
                else:
                    parsed = parse_standings_text(text, doc, headers)
                    if not parsed:
                        failures.append(f"{doc.key} standings: no rows parsed")
                    else:
                        all_standings.append(parsed)

                snapshots.append(
                    {
                        "division": doc.division,
                        "section": doc.section,
                        "kind": kind,
                        "url": url,
                        "sha256": sha256(pdf_bytes),
                        "bytes": len(pdf_bytes),
                        "headers": headers,
                        "extractedText": text,
                        "parsedCount": len(parsed) if isinstance(parsed, list) else sum(len(g["rows"]) for g in parsed.get("groups", [])) if parsed else 0,
                    }
                )

    generated = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "documents": [asdict(doc) for doc in docs],
        "snapshots": snapshots,
        "scheduleGames": sorted(all_games, key=lambda game: (game["date"], game["time"], game["division"], game["section"], game["home"])),
        "standings": sorted(all_standings, key=lambda table: (table["division"], table["section"])),
        "failures": failures,
    }
    write_if_changed(GENERATED_JSON, serialize_json(generated))

    if failures and args.require_complete:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        print("Refusing to patch static chunks because --require-complete is enabled.", file=sys.stderr)
        return 1

    if args.patch_static:
        changed = patch_static_chunks(generated["scheduleGames"], generated["standings"])
        for path in changed:
            print(f"patched {path.relative_to(ROOT)}")

    print(
        f"Processed {len(docs)} sections, parsed {len(all_games)} games and "
        f"{sum(len(group['rows']) for table in all_standings for group in table['groups'])} standing rows."
    )
    if failures:
        print("Parser warnings:")
        for failure in failures:
            print(f"- {failure}")
    return 0


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch-static", action="store_true", help="Rewrite the bundled schedule/standings JS chunks.")
    parser.add_argument("--require-complete", action="store_true", help="Fail if any linked PDF cannot be parsed.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    return sync(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
