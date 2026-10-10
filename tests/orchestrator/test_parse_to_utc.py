import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.orchestrator.match_resolver import parse_to_utc

"""
Dokumentace chování parse_to_utc():
1. Vstup string ISO (např. "2026-10-20T20:00:00Z" nebo "2026-10-20 20:00:00+02:00"):
   - "Z" je převedeno na "+00:00" a parsováno přes datetime.fromisoformat().
   - Pokud řetězec neobsahuje explicitní offset, datetime je zpočátku naive.
2. Vstup datetime objekt:
   - Pokud je dt.tzinfo je None (naive datetime), je mu přiřazeno časové pásmo podle parametru default_tz_name (default: Europe/Prague).
   - Neplatné nebo neznámé název časového pásma (nebo prázdný název) vyvolá ValueError s českou chybovou hláškou.
3. Výstup:
   - Všechny platné datetimes jsou zkonvertovány do UTC vraceny s tzinfo=timezone.utc.
4. Neplatné vstupy (ne-string/ne-datetime, poškozený formát):
   - Vyvolají ValueError.
"""


def test_parse_to_utc_with_z_suffix():
    dt = parse_to_utc("2026-10-20T20:00:00Z")
    assert dt == datetime(2026, 10, 20, 20, 0, 0, tzinfo=timezone.utc)


def test_parse_to_utc_with_explicit_offset():
    dt = parse_to_utc("2026-10-20T22:00:00+02:00")
    assert dt == datetime(2026, 10, 20, 20, 0, 0, tzinfo=timezone.utc)


def test_parse_to_utc_naive_string_uses_default_timezone():
    # Europe/Prague in October is CEST (+02:00)
    dt = parse_to_utc("2026-10-20T22:00:00", default_tz_name="Europe/Prague")
    assert dt == datetime(2026, 10, 20, 20, 0, 0, tzinfo=timezone.utc)


def test_parse_to_utc_invalid_timezone():
    with pytest.raises(ValueError, match="Neplatné nebo neznámé časové pásmo"):
        parse_to_utc("2026-10-20T20:00:00", default_tz_name="Invalid/Timezone")


def test_parse_to_utc_empty_timezone():
    with pytest.raises(ValueError, match="Neplatné nebo chybějící název časového pásma"):
        parse_to_utc("2026-10-20T20:00:00", default_tz_name="   ")


def test_parse_to_utc_invalid_format_raises_value_error():
    with pytest.raises(ValueError):
        parse_to_utc("invalid-date-string")
