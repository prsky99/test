"""Canonical epoch seconds for report metadata, preserving explicit UTC offsets."""
from datetime import datetime, timezone
import math


def report_timestamp(value, *, legacy_utc=False):
    if type(value) in (int,float):
        result=float(value)
    elif type(value) is str and 1 <= len(value) <= 64:
        try:
            parsed=datetime.fromisoformat(value.strip().replace('Z','+00:00'))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                # Historical SQLite CURRENT_TIMESTAMP is explicitly UTC.
                if not legacy_utc: raise ValueError()
                parsed=parsed.replace(tzinfo=timezone.utc)
            result=parsed.timestamp()
        except (ValueError,OverflowError):
            raise ValueError('invalid_report_timestamp') from None
    else:
        raise ValueError('invalid_report_timestamp')
    if not math.isfinite(result) or not 0 < result < 253402300800:
        raise ValueError('invalid_report_timestamp')
    return result
