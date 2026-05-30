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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_CHUNK = ROOT / "_next/static/chunks/app/schedule/page-4d7f3905a5da1900.js"
STANDINGS_CHUNK = ROOT / "_next/static/chunks/app/standings/page-c30f85e5d0d57d3c.js"
GENERATED_DIR = ROOT / "data/generated"
GENERATED_JSON = GENERATED_DIR / "lcybl-official-data.json"
USER_AGENT = "LCYBL-static-data-sync/1.0 (+https://github.com/)"
DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})\b|\b\d{4}-\d{2}-\d{2}\b")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", re.IGNORECASE)


@dataclass(frozen=True)
class OfficialDocument:
    division: str
    section: int
    standings_url: str | None
    scores_url: str

    @property
    def key(self) -> str:
        return f"{self.division}-section-{self.section}"


@dataclass
class PdfExtraction:
    text: str
    tables: list[list[list[str]]]


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
    """Read the official PDF URLs from the bundled static chunks."""
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


def clean_cell(value: Any) -> str:
    return re.sub(r"[ \t]+", " ", str(value or "").replace("\u00a0", " ").strip())


def extract_pdf(data: bytes) -> PdfExtraction:
    """Extract both text and table rows from a PDF.

    The LCYBL files are Excel sheets printed to PDF. Plain text extraction often
    returns the sheet in column order, which is why the original parser found no
    games. pdfplumber's line-based table extraction keeps each spreadsheet row
    together, and the text fallback is retained only for unusual PDFs.
    """
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - exercised in CI if deps missing
        raise RuntimeError("Install parser dependencies with `python -m pip install -r requirements-lcybl-sync.txt`.") from exc

    text_pages: list[str] = []
    tables: list[list[list[str]]] = []
    line_table_settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 4,
        "join_tolerance": 4,
        "intersection_tolerance": 6,
        "text_x_tolerance": 2,
        "text_y_tolerance": 3,
    }
    text_table_settings = {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "snap_tolerance": 4,
        "join_tolerance": 4,
        "intersection_tolerance": 6,
        "min_words_vertical": 2,
        "min_words_horizontal": 1,
        "text_x_tolerance": 2,
        "text_y_tolerance": 3,
    }
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text(layout=True, x_tolerance=2, y_tolerance=3) or ""
            text_pages.append(f"\n--- page {page_number} ---\n{page_text}")
            page_tables = page.extract_tables(line_table_settings) or []
            if not page_tables:
                page_tables = page.extract_tables(text_table_settings) or []
            for table in page_tables:
                cleaned = [[clean_cell(cell) for cell in row] for row in table]
                cleaned = [row for row in cleaned if any(row)]
                if cleaned:
                    tables.append(cleaned)
    return PdfExtraction(text="\n".join(text_pages), tables=tables)


def normalized_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\u00a0", " ").splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def parse_date(value: str) -> str | None:
    value = value.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_number(value: str) -> int | float | None:
    value = value.strip().replace(",", "").replace("%", "")
    if re.fullmatch(r"\d+", value):
        return int(value)
    if re.fullmatch(r"\d+\.\d+", value):
        return float(value)
    return None


def first_match(pattern: re.Pattern[str], values: Iterable[str]) -> str | None:
    for value in values:
        match = pattern.search(value)
        if match:
            return match.group(0)
    return None


def date_from_values(values: Iterable[str]) -> str | None:
    raw = first_match(DATE_RE, values)
    return parse_date(raw) if raw else None


def time_from_values(values: Iterable[str]) -> str | None:
    raw = first_match(TIME_RE, values)
    return re.sub(r"\s+", " ", raw.upper()) if raw else None


def is_header_row(row: list[str]) -> bool:
    lowered = " ".join(row).lower()
    return any(word in lowered for word in ("date", "time", "field", "location", "home", "visitor", "visiting", "away"))


def header_index(headers: list[str], *needles: str, exclude: tuple[str, ...] = ()) -> int | None:
    for index, header in enumerate(headers):
        lower = header.lower()
        if all(needle in lower for needle in needles) and not any(item in lower for item in exclude):
            return index
    return None


def first_index(*indexes: int | None) -> int | None:
    return next((index for index in indexes if index is not None), None)


def value_at(row: list[str], index: int | None) -> str:
    return row[index].strip() if index is not None and index < len(row) else ""


def row_has_schedule_data(row: list[str]) -> bool:
    return bool(date_from_values(row) and time_from_values(row))


def parse_schedule_table_row(row: list[str], headers: list[str] | None, doc: OfficialDocument, row_number: int) -> dict[str, Any] | None:
    row = [clean_cell(cell) for cell in row]
    if not row_has_schedule_data(row):
        return None

    date = date_from_values(row)
    time = time_from_values(row)
    if not date or not time:
        return None

    date_idx = next((index for index, cell in enumerate(row) if DATE_RE.search(cell)), None)
    time_idx = next((index for index, cell in enumerate(row) if TIME_RE.search(cell)), None)
    home = away = field = ""
    home_score: int | None = None
    away_score: int | None = None

    if headers:
        normalized_headers = [header.lower() for header in headers]
        field_idx = first_index(header_index(normalized_headers, "field"), header_index(normalized_headers, "location"))
        home_idx = header_index(normalized_headers, "home", exclude=("score",))
        away_idx = first_index(
            header_index(normalized_headers, "visitor", exclude=("score",)),
            header_index(normalized_headers, "visiting", exclude=("score",)),
            header_index(normalized_headers, "away", exclude=("score",)),
        )
        home_score_idx = first_index(header_index(normalized_headers, "home", "score"), header_index(normalized_headers, "h", "score"))
        away_score_idx = first_index(
            header_index(normalized_headers, "visitor", "score"),
            header_index(normalized_headers, "visiting", "score"),
            header_index(normalized_headers, "away", "score"),
            header_index(normalized_headers, "v", "score"),
        )
        home = value_at(row, home_idx)
        away = value_at(row, away_idx)
        field = value_at(row, field_idx)
        maybe_home_score = parse_number(value_at(row, home_score_idx))
        maybe_away_score = parse_number(value_at(row, away_score_idx))
        home_score = maybe_home_score if isinstance(maybe_home_score, int) else None
        away_score = maybe_away_score if isinstance(maybe_away_score, int) else None

    if not home or not away:
        remaining = [cell for index, cell in enumerate(row) if index not in {date_idx, time_idx} and cell]
        if len(remaining) == 1:
            collapsed = remaining[0]
            score_matches = list(re.finditer(r"(?<!\S)\d{1,2}(?!\S)", collapsed))
            if len(score_matches) >= 2:
                first, second = score_matches[0], score_matches[1]
                home = collapsed[: first.start()].strip(" -|")
                home_score = int(first.group())
                away = collapsed[first.end() : second.start()].strip(" -|")
                away_score = int(second.group())
                field = field or collapsed[second.end() :].strip(" -|")
        if not home or not away:
            numeric_positions = [index for index, cell in enumerate(remaining) if isinstance(parse_number(cell), int)]
            if len(numeric_positions) >= 2:
                first, second = numeric_positions[0], numeric_positions[1]
                home = " ".join(remaining[:first]).strip()
                home_score = int(parse_number(remaining[first]) or 0)
                away = " ".join(remaining[first + 1 : second]).strip()
                away_score = int(parse_number(remaining[second]) or 0)
                field = field or " ".join(remaining[second + 1 :]).strip()
            elif len(remaining) >= 3:
                # Scheduled rows often do not have scores yet.
                home, away = remaining[0], remaining[1]
                field = field or " ".join(remaining[2:]).strip()

    if not home or not away:
        return None

    game: dict[str, Any] = {
        "id": f"{doc.division}-{doc.section}-{row_number}",
        "date": date,
        "time": time,
        "division": doc.division,
        "section": f"Section {doc.section}",
        "home": home,
        "away": away,
        "field": field,
        "status": "final" if home_score is not None and away_score is not None else "scheduled",
    }
    if home_score is not None:
        game["homeScore"] = home_score
    if away_score is not None:
        game["awayScore"] = away_score
    return game


def parse_schedule_text_fallback(text: str, doc: OfficialDocument, start_index: int) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for line in normalized_lines(text):
        if any(skip in line.lower() for skip in ("date time", "lancaster county", "section", "scores")):
            continue
        if not DATE_RE.search(line) or not TIME_RE.search(line):
            continue
        # Convert a text line into fake cells by splitting around large gaps when
        # available; otherwise the fallback row parser can still use numeric
        # score positions in the collapsed line.
        cells = [cell.strip() for cell in re.split(r"\s{2,}|\t+", line) if cell.strip()]
        if len(cells) == 1:
            cells = [DATE_RE.search(line).group(0), TIME_RE.search(line).group(0), line[TIME_RE.search(line).end() :].strip()]
        game = parse_schedule_table_row(cells, None, doc, start_index + len(games))
        if game:
            games.append(game)
    return games


def parse_schedule(extraction: PdfExtraction, doc: OfficialDocument) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for table in extraction.tables:
        headers: list[str] | None = None
        for row in table:
            if is_header_row(row):
                headers = [clean_cell(cell) for cell in row]
                continue
            game = parse_schedule_table_row(row, headers, doc, len(games))
            if game:
                games.append(game)

    if not games:
        games.extend(parse_schedule_text_fallback(extraction.text, doc, 0))

    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for game in games:
        key = (game["date"], game["time"], game["home"], game["away"], game.get("homeScore"), game.get("awayScore"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(game)
    return unique


def make_standing_row(cells: list[str], rank: int) -> dict[str, Any] | None:
    if len(cells) < 8:
        return None
    metrics = [parse_number(cell) for cell in cells[-7:]]
    if any(metric is None for metric in metrics):
        return None
    team = " ".join(cells[:-7]).strip(" -|")
    if not team:
        return None
    return {
        "team": re.sub(r"\s+", " ", team),
        "wins": int(metrics[0]),
        "losses": int(metrics[1]),
        "ties": int(metrics[2]),
        "pct": float(metrics[3]),
        "points": int(metrics[4]),
        "runsAllowed": int(metrics[5]),
        "gamesRemaining": int(metrics[6]),
        "champion": rank == 0,
    }


def parse_standings(extraction: PdfExtraction, doc: OfficialDocument, headers: dict[str, str]) -> dict[str, Any] | None:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] = {"rows": []}

    def add_group_if_needed() -> None:
        nonlocal current
        if current["rows"]:
            groups.append(current)
            current = {"rows": []}

    for table in extraction.tables:
        for row in table:
            cells = [clean_cell(cell) for cell in row if clean_cell(cell)]
            if not cells:
                continue
            line = " ".join(cells)
            lower = line.lower()
            if "division" in lower and not any(parse_number(cell) is not None for cell in cells[-4:]):
                add_group_if_needed()
                current = {"name": line.strip(" -|"), "rows": []}
                continue
            if is_header_row(cells) or lower.startswith(("team ", "w ", "wins ")):
                continue
            standing = make_standing_row(cells, len(current["rows"]))
            if standing:
                current["rows"].append(standing)

    add_group_if_needed()

    if not groups:
        # Text fallback for PDFs where table lines are already row-oriented.
        current = {"rows": []}
        for line in normalized_lines(extraction.text):
            cells = line.split()
            if "division" in line.lower():
                add_group_if_needed()
                current = {"name": line.strip(" -|"), "rows": []}
                continue
            standing = make_standing_row(cells, len(current["rows"]))
            if standing:
                current["rows"].append(standing)
        add_group_if_needed()

    if not groups:
        return None

    updated = headers.get("Last-Modified") or headers.get("last-modified")
    if not updated:
        updated = dt.date.today().strftime("%-m/%-d/%Y") if sys.platform != "win32" else dt.date.today().strftime("%#m/%#d/%Y")

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


def debug_dump(debug_dump_dir: Path | None, doc: OfficialDocument, kind: str, extraction: PdfExtraction) -> None:
    if not debug_dump_dir:
        return
    debug_dump_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{doc.key}-{kind}"
    (debug_dump_dir / f"{prefix}.txt").write_text(extraction.text, encoding="utf-8")
    (debug_dump_dir / f"{prefix}.tables.json").write_text(serialize_json(extraction.tables), encoding="utf-8")


def sync(args: argparse.Namespace) -> int:
    docs = extract_official_documents()
    all_games: list[dict[str, Any]] = []
    all_standings: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    failures: list[str] = []
    debug_dump_dir = Path(args.debug_dump_dir) if args.debug_dump_dir else None

    for doc in docs:
        for kind, url in (("scores", doc.scores_url), ("standings", doc.standings_url)):
            if not url:
                continue
            try:
                pdf_bytes, headers = download(url)
                extraction = extract_pdf(pdf_bytes)
            except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
                failures.append(f"{doc.key} {kind}: download/extract failed: {exc}")
                continue

            debug_dump(debug_dump_dir, doc, kind, extraction)
            parsed: Any
            if kind == "scores":
                parsed = parse_schedule(extraction, doc)
                if not parsed:
                    failures.append(f"{doc.key} scores: no games parsed")
                all_games.extend(parsed)
            else:
                parsed = parse_standings(extraction, doc, headers)
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
                    "tableCount": len(extraction.tables),
                    "textCharacterCount": len(extraction.text),
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
    parser.add_argument("--debug-dump-dir", help="Optional directory for extracted text/tables when debugging parser failures.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    return sync(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
