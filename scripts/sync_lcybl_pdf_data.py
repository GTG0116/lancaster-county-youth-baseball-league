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
SCHEDULE_CHUNK = ROOT / "_next/static/chunks/app/schedule/page-4d7f3905a5da1900.js"
STANDINGS_CHUNK = ROOT / "_next/static/chunks/app/standings/page-c30f85e5d0d57d3c.js"
GENERATED_DIR = ROOT / "data/generated"
GENERATED_JSON = GENERATED_DIR / "lcybl-official-data.json"
USER_AGENT = "LCYBL-static-data-sync/1.0 (+https://github.com/)"


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


def make_standing_row(match: re.Match[str], rank: int) -> dict[str, Any]:
    row = {
        "team": re.sub(r"\s+", " ", match.group("team")).strip(" -|"),
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

    for line in normalized_lines(text):
        lower = line.lower()
        if not line or lower.startswith("--- page"):
            continue
        if "division" in lower and not row_re.match(line):
            name = re.sub(r"\s+", " ", line).strip(" -|")
            if current["rows"]:
                groups.append(current)
            current = {"name": name, "rows": []}
            continue
        match = row_re.match(line)
        if match:
            current["rows"].append(make_standing_row(match, len(current["rows"])))

    if current["rows"]:
        groups.append(current)
    if not groups:
        return None

    last_modified = headers.get("Last-Modified") or headers.get("last-modified")
    if last_modified:
        updated = last_modified
    else:
        updated = dt.date.today().strftime("%-m/%-d/%Y") if sys.platform != "win32" else dt.date.today().strftime("%#m/%#d/%Y")

    # If there is only one unnamed group, keep the previous UI style.
    for group in groups:
        if group.get("name", "").lower().startswith(("standings", "team")):
            group.pop("name", None)

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


def patch_static_chunks(games: list[dict[str, Any]], standings: list[dict[str, Any]]) -> list[Path]:
    changed: list[Path] = []
    if games:
        replacement = f"let S={serialize_js(games)}"
        if patch_between(SCHEDULE_CHUNK, 'let p="6:00 PM",S=', ';function x()', replacement):
            changed.append(SCHEDULE_CHUNK)
    if standings:
        replacement = f"let c={serialize_js(standings)}"
        if patch_between(STANDINGS_CHUNK, "let c=", ";function l(e)", replacement):
            changed.append(STANDINGS_CHUNK)
    return changed


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync(args: argparse.Namespace) -> int:
    docs = extract_official_documents()
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
