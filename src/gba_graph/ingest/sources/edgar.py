"""SEC filing metadata helpers for explicit, approved EDGAR plans."""
from datetime import date


def filing_date(record: dict) -> date | None:
    value = record.get("filingDate")
    return date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None


def archive_document_url(cik: str, accession: str, filename: str) -> str:
    cik_numeric = str(int(cik))
    accession_compact = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_numeric}/{accession_compact}/{filename}"
