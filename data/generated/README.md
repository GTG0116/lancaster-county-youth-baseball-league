# Generated LCYBL data

This directory is maintained by `.github/workflows/sync-lcybl-pdf-data.yml`.

The workflow downloads the official LCYBL PDF documents linked from the static
site, extracts spreadsheet-style tables with `pdfplumber`, parses schedules and
standings, and rewrites the static schedule/standings bundles when every
section parses successfully.

Do not edit generated JSON files by hand; run `scripts/sync_lcybl_pdf_data.py`
instead. If parsing fails in GitHub Actions, download the `lcybl-pdf-parser-debug`
artifact to inspect the extracted text and table rows.
