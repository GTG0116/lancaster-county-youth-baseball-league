# Generated LCYBL data

This directory is maintained by `.github/workflows/sync-lcybl-pdf-data.yml`.

The workflow downloads the official LCYBL PDF documents linked from the static
site, extracts their text, parses schedules and standings, and rewrites the
static schedule/standings bundles when every section parses successfully.

Do not edit generated JSON files by hand; run `scripts/sync_lcybl_pdf_data.py`
instead.
