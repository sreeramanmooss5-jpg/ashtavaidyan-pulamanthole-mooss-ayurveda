import datetime
import json
import logging
import sys
from zoneinfo import ZoneInfo


def get_logger(name: str, tz_name: str = "Asia/Kolkata") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._tz = ZoneInfo(tz_name)
    return logger


def log_event(logger: logging.Logger, level: str, event: str, **fields) -> None:
    tz = getattr(logger, "_tz", ZoneInfo("Asia/Kolkata"))
    now_ist = datetime.datetime.now(tz).isoformat()
    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    payload = {
        "timestamp_ist": now_ist,
        "timestamp_utc": now_utc,
        "level": level.upper(),
        "event": event,
        **fields,
    }
    line = json.dumps(payload, default=str)
    if level.upper() == "ERROR":
        logger.error(line)
    elif level.upper() == "WARN":
        logger.warning(line)
    else:
        logger.info(line)
