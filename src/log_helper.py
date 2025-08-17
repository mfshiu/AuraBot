# log_helper.py
import atexit
import logging
import logging.handlers as _handlers
import multiprocessing as mp
import os
import sys
import threading
from datetime import datetime

VERBOSE_LEVEL = 5
VERBOSE_NAME = "VERBOSE"

def _install_verbose_level():
    if logging.getLevelName(VERBOSE_LEVEL) != VERBOSE_NAME:
        logging.addLevelName(VERBOSE_LEVEL, VERBOSE_NAME)

    def verbose(self, message, *args, **kwargs):
        if self.isEnabledFor(VERBOSE_LEVEL):
            self._log(VERBOSE_LEVEL, message, args, **kwargs)

    if not hasattr(logging.Logger, "verbose"):
        logging.Logger.verbose = verbose


class SizeAndTimeRotatingFileHandler(_handlers.TimedRotatingFileHandler):
    """
    同時依時間（如每日）與大小（預設 5MB）切檔。
    """
    def __init__(self, filename, when="midnight", interval=1, backupCount=30,
                 encoding="utf-8", delay=False, utc=False, atTime=None,
                 maxBytes=5 * 1024 * 1024):
        super().__init__(filename, when=when, interval=interval,
                         backupCount=backupCount, encoding=encoding,
                         delay=delay, utc=utc, atTime=atTime)
        self.maxBytes = maxBytes

    def shouldRollover(self, record):
        time_cond = super().shouldRollover(record)

        if self.stream is None:
            self.stream = self._open()
        try:
            self.stream.flush()
            cur_size = os.stat(self.baseFilename).st_size
        except FileNotFoundError:
            cur_size = 0

        msg = (self.format(record) + "\n").encode(self.encoding or "utf-8")
        size_cond = self.maxBytes > 0 and (cur_size + len(msg) >= self.maxBytes)
        return time_cond or size_cond


class _RouterHandler(logging.Handler):
    """
    依 record.name 路由到對應的檔案 handler。
    """
    def __init__(self, fmt, datefmt, log_dir, when, max_bytes, backup_count):
        super().__init__()
        self.fmt = fmt
        self.datefmt = datefmt
        self.log_dir = log_dir
        self.when = when
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._handlers = {}
        self._lock = threading.Lock()

    def _get_or_create(self, logger_name):
        with self._lock:
            h = self._handlers.get(logger_name)
            if h:
                return h
            os.makedirs(self.log_dir, exist_ok=True)
            # 檔名＝log name
            filepath = os.path.join(self.log_dir, f"{logger_name}.log")
            h = SizeAndTimeRotatingFileHandler(
                filename=filepath,
                when=self.when,
                interval=1,
                backupCount=self.backup_count,
                maxBytes=self.max_bytes,
                encoding="utf-8",
            )
            formatter = logging.Formatter(self.fmt, self.datefmt)
            h.setFormatter(formatter)
            h.setLevel(VERBOSE_LEVEL)  # 讓 VERBOSE 也能寫入
            self._handlers[logger_name] = h
            return h

    def emit(self, record):
        try:
            handler = self._get_or_create(record.name)
            handler.emit(record)
        except Exception:
            self.handleError(record)

    def close(self):
        with self._lock:
            for h in self._handlers.values():
                try:
                    h.close()
                except Exception:
                    pass
            self._handlers.clear()
        super().close()


class _LogBus:
    """
    全域單例：集中 QueueListener + RouterHandler。
    """
    _started = False
    _lock = threading.Lock()
    _queue = None
    _listener = None
    _router = None

    @classmethod
    def start(cls, *, log_dir="logs", when="midnight", max_bytes=5*1024*1024,
              backup_count=30,
              fmt="[%(asctime)s] [%(processName)s %(threadName)s] [%(levelname)s] %(name)s: %(message)s",
              datefmt="%Y-%m-%d %H:%M:%S"):
        with cls._lock:
            if cls._started:
                return
            _install_verbose_level()
            cls._queue = mp.Queue(-1)
            cls._router = _RouterHandler(
                fmt=fmt, datefmt=datefmt, log_dir=log_dir,
                when=when, max_bytes=max_bytes, backup_count=backup_count
            )
            root = logging.getLogger()
            root.setLevel(VERBOSE_LEVEL)

            cls._listener = _handlers.QueueListener(cls._queue, cls._router, respect_handler_level=True)
            cls._listener.start()
            cls._started = True

            def _stop():
                try:
                    cls._listener.stop()
                except Exception:
                    pass
                try:
                    cls._router.close()
                except Exception:
                    pass

            atexit.register(_stop)

    @classmethod
    def queue(cls):
        if not cls._started:
            cls.start()  # 使用預設設定啟動
        return cls._queue


class LogHelper:
    """
    使用方式：
        logger = LogHelper.get_logger("my_log")  # 檔名= logs/my_log.log
        logger.info("info")
        logger.verbosr("lowest level message")  # 或 logger.verbose(...)
    """
    _configured = False
    _defaults = dict(
        log_dir="logs",
        when="midnight",
        max_bytes=5*1024*1024,
        backup_count=30,
        fmt="[%(asctime)s] [%(processName)s %(threadName)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    @classmethod
    def configure(cls, **kwargs):
        """
        可選：先呼叫以調整預設（如 log_dir、backup_count 等）。
        """
        cls._defaults.update(kwargs)
        # 重新啟動 bus（若尚未啟動則無事）
        if _LogBus._started:
            # 若需要動態調整，可在此實作重啟；簡化起見不熱重啟。
            pass

    @classmethod
    def get_logger(cls, name: str):
        """
        取得指定 log name 的 logger。
        - logger.name = 你傳入的 name
        - 寫入檔名 = logs/<name>.log
        """
        if not _LogBus._started:
            _LogBus.start(**cls._defaults)

        q = _LogBus.queue()
        logger = logging.getLogger(name)

        # 只掛一次 QueueHandler
        if not any(isinstance(h, _handlers.QueueHandler) for h in logger.handlers):
            qh = _handlers.QueueHandler(q)
            logger.addHandler(qh)
            logger.setLevel(VERBOSE_LEVEL)
            logger.propagate = True
        return logger


# ---- 範例（可刪）----------------------------------------------
if __name__ == "__main__":
    LogHelper.configure(log_dir="logs", backup_count=15)
    logA = LogHelper.get_logger("service-A")
    logB = LogHelper.get_logger("service-B")

    logB.verbose("B verbose")
    logB.error("B error")
