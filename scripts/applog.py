"""공용 기록(로그) 설정: data/logs/app.log 에 남기고, API 키는 어떤 경우에도 가린다."""
import logging
import logging.handlers

from step1 import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_FILE = LOG_DIR / "app.log"

# 설정 전에는 기록을 조용히 버림 (테스트 화면에 오류 추적이 쏟아지지 않게)
logging.getLogger("shorts").addHandler(logging.NullHandler())


class RedactKeyFilter(logging.Filter):
    """기록되는 글에 .env 의 API 키가 섞이면 [키 숨김] 으로 바꾼다."""

    def filter(self, record):
        try:
            from config import _read_env_file
            secrets = [v for k, v in _read_env_file().items() if "KEY" in k.upper() and len(v) >= 8]
        except Exception:
            secrets = []
        if secrets:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + logging.Formatter().formatException(record.exc_info)
                record.exc_info = None
            for s in secrets:
                message = message.replace(s, "[키 숨김]")
            record.msg, record.args = message, ()
        return True


def setup_logging(level=logging.INFO, log_dir=None):
    root = logging.getLogger("shorts")
    if any(getattr(h, "_shorts", False) for h in root.handlers):
        return root
    log_dir = log_dir or LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_dir / "app.log", maxBytes=2_000_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactKeyFilter())
    handler._shorts = True
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    return root
