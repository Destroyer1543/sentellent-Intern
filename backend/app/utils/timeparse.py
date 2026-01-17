import dateparser
from datetime import timedelta
import pytz

TZ = "Asia/Kolkata"

def parse_datetime_natural(text: str):
    dt = dateparser.parse(
        text,
        settings={
            "TIMEZONE": TZ,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
        }
    )
    return dt

def default_end(dt, minutes=30):
    return dt + timedelta(minutes=minutes)
