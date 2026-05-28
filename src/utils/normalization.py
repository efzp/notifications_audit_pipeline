import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from typing import Any


def clean_text(value: Any) -> str | None:
    if value is None:
        return None

    clean_value = re.sub(r"\s+", " ", str(value)).strip()
    return clean_value or None


def normalize_db_string(value: Any) -> str | None:
    clean_value = clean_text(value)
    if clean_value is None:
        return None

    normalized = unicodedata.normalize("NFKD", clean_value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    db_value = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value)
    return db_value.strip("_").lower() or None


def normalize_email(value: Any) -> str | None:
    clean_value = clean_text(value)
    if clean_value is None:
        return None

    return clean_value.lower()


def normalize_document(value: Any) -> str | None:
    clean_value = clean_text(value)
    if clean_value is None:
        return None

    document = re.sub(r"\D+", "", clean_value)
    return document or None


def normalize_radicado(value: Any) -> str | None:
    clean_value = clean_text(value)
    if clean_value is None:
        return None

    radicado = re.sub(r"[^A-Za-z0-9]+", "", clean_value)
    return radicado.upper() or None


def normalize_date(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    clean_value = clean_text(value)
    if clean_value is None:
        return None

    for date_format in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
    ):
        try:
            return datetime.strptime(clean_value, date_format).date().isoformat()
        except ValueError:
            continue

    return None


def json_dumps_safe(value: Any) -> str | None:
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False, default=str)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_dict(value: dict[str, Any]) -> str:
    stable_json = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256_text(stable_json)
