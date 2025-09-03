# log_helper.py
from __future__ import annotations
import atexit
import logging
import logging.handlers as _handlers
import multiprocessing as mp
import os
import sys
import threading
from typing import List, Dict, Optional

# ---- VERBOSE level（比 DEBUG 更低）----
VERBOSE_LEVEL = 5
VERBOSE_NAME = "VERBOSE"

class VerboseLogger(logging.Logger):
    def verbose(self, msg: str, *args, **kwargs) -> None:
        if self.isEnabledFor(VERBOSE_LEVEL):
            self._log(VERBOSE_LEVEL, msg, args, **kwargs)

def _install_verbose_logger_class() -> None:
    if logging.getLevelName(VERBOSE_LEVEL) != VERBOSE_NAME:
        logging.addLevelName(VERBOSE_LEVEL, VERBOSE_NAME)
    # 讓 getLogger() 取得的是 VerboseLogger（Pylance 就認得 .verbose）
    if not isinstance(logging.getLoggerClass(), type) or logging.getLoggerClass() is not VerboseLogger:
        logging.setLoggerClass(VerboseLogger)

# ---- 轉檔：同時依「每日」與「大小」 ----
class SizeAndTimeRotatingFileHandler(_handlers.TimedRotatingFileHandler):
    def __init__(
        self, filename: str, when: str = "midnight", interval: int = 1,
        backupCount: int = 30, encoding: str = "utf-8", delay: bool = False,
        utc: bool = False, atTime=None, maxBytes: int = 5 * 1024 * 1024
    ) -> None:
        super().__init__(filename, when=when, interval=interval, backupCount=backupCount,
                         encoding=encoding, delay=delay, utc=utc, atTime=atTime)
        self.maxBytes = maxBytes

    def shouldRollover(self, record: logging.LogRecord) -> bool:
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
        return time_cond or size_cond # type: ignore

# ---- 檔案路由器：依 logger.name -> logs/{name}.log ----
class RouterHandler(logging.Handler):
    def __init__(self, fmt: str, datefmt: str, log_dir: str,
                 when: str, max_bytes: int, backup_count: int) -> None:
        super().__init__(level=VERBOSE_LEVEL)
        self.fmt = fmt
        self.datefmt = datefmt
        self.log_dir = log_dir
        self.when = when
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._handlers: Dict[str, logging.Handler] = {}
        self._lock = threading.Lock()

    def _get_or_create(self, logger_name: str) -> logging.Handler:
        with self._lock:
            h = self._handlers.get(logger_name)
            if h:
                return h
            os.makedirs(self.log_dir, exist_ok=True)
            filepath = os.path.join(self.log_dir, f"{logger_name}.log")
            h = SizeAndTimeRotatingFileHandler(
                filename=filepath, when=self.when, interval=1,
                backupCount=self.backup_count, maxBytes=self.max_bytes, encoding="utf-8"
            )
            h.setFormatter(logging.Formatter(self.fmt, self.datefmt))
            h.setLevel(VERBOSE_LEVEL)
            self._handlers[logger_name] = h
            return h

    def emit(self, record: logging.LogRecord) -> None:
        try:
            handler = self._get_or_create(record.name)
            handler.emit(record)
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        with self._lock:
            for h in self._handlers.values():
                try:
                    h.close()
                except Exception:
                    pass
            self._handlers.clear()
        super().close()

# ---- Console 彩色 formatter（colorama 可選）----
try:
    from colorama import Fore, Back, Style, init as colorama_init
    colorama_init()
    _USE_COLOR = True
except Exception:
    _USE_COLOR = False

class ColorFormatter(logging.Formatter):
    LEVEL_COLORS = {
        VERBOSE_LEVEL: (lambda s: Style.DIM + Fore.WHITE + s + Style.RESET_ALL),
        logging.DEBUG:  (lambda s: Fore.WHITE  + s + Style.RESET_ALL),
        logging.INFO:   (lambda s: Fore.BLUE  + s + Style.RESET_ALL),
        logging.WARNING:(lambda s: Fore.YELLOW + s + Style.RESET_ALL),
        logging.ERROR:  (lambda s: Fore.RED    + s + Style.RESET_ALL),
        logging.CRITICAL:(lambda s: Back.RED + Fore.WHITE + s + Style.RESET_ALL),
    }
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        if _USE_COLOR:
            color_fn = self.LEVEL_COLORS.get(record.levelno)
            if color_fn:
                return color_fn(base)
        return base

# ---- 全域 LogBus：QueueListener 集中寫入 ----
class _LogBus:
    _started = False
    _lock = threading.Lock()
    _queue: Optional[mp.Queue] = None
    _listener: Optional[_handlers.QueueListener] = None
    _router: Optional[RouterHandler] = None

    @classmethod
    def start(cls, *, log_dir: str = "logs", when: str = "midnight",
              max_bytes: int = 5 * 1024 * 1024, backup_count: int = 30,
              fmt: str = "[%(asctime)s] [%(processName)s %(threadName)s] [%(levelname)s] %(name)s: %(message)s",
              datefmt: str = "%Y-%m-%d %H:%M:%S",
              console: bool = True,
              console_level: int = VERBOSE_LEVEL,
              console_fmt: str = "%(asctime)s %(levelname)s %(name)s: %(message)s") -> None:
        with cls._lock:
            if cls._started:
                return
            _install_verbose_logger_class()
            cls._queue = mp.Queue(-1)

            # file router
            cls._router = RouterHandler(fmt=fmt, datefmt=datefmt, log_dir=log_dir,
                                        when=when, max_bytes=max_bytes, backup_count=backup_count)

            # handlers list（型別明確）
            handlers: List[logging.Handler] = [cls._router]

            if console:
                ch = logging.StreamHandler(sys.stdout)
                ch.setLevel(console_level)
                ch.setFormatter(ColorFormatter(console_fmt, datefmt) if _USE_COLOR
                                else logging.Formatter(console_fmt, datefmt))
                handlers.append(ch)

            root = logging.getLogger()
            root.setLevel(VERBOSE_LEVEL)

            cls._listener = _handlers.QueueListener(cls._queue, *handlers, respect_handler_level=True)
            cls._listener.start()
            cls._started = True

            def _stop() -> None:
                try:
                    if cls._listener:
                        cls._listener.stop()
                except Exception:
                    pass
                try:
                    if cls._router:
                        cls._router.close()
                except Exception:
                    pass
            atexit.register(_stop)

    @classmethod
    def queue(cls) -> mp.Queue:
        if not cls._started:
            cls.start()
        assert cls._queue is not None
        return cls._queue

# ---- 公開 Helper ----
class LogHelper:
    """使用：
        logger = LogHelper.get_logger("service-A")  # 檔名= logs/service-A.log
        logger.info("hello")
        logger.verbose("details")
    """
    _defaults = dict(
        log_dir="logs",
        when="midnight",
        max_bytes=5*1024*1024,
        backup_count=30,
        fmt="[%(asctime)s] [%(processName)s %(threadName)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        console=True,
    )

    @classmethod
    def configure(cls, **kwargs) -> None:
        cls._defaults.update(kwargs)

    @classmethod
    def get_logger(cls, name: str) -> VerboseLogger:
        if not _LogBus._started:
            _LogBus.start(**cls._defaults) # type: ignore
        q = _LogBus.queue()
        logger = logging.getLogger(name)  # type: ignore[assignment]
        # 確保是 VerboseLogger
        if not isinstance(logger, VerboseLogger):
            logger.__class__ = VerboseLogger  # 避免極端情況下的型別流失
        if not any(isinstance(h, _handlers.QueueHandler) for h in logger.handlers):
            qh = _handlers.QueueHandler(q)
            logger.addHandler(qh)
            logger.setLevel(VERBOSE_LEVEL)
            logger.propagate = True
        return logger  # type: ignore[return-value]

# ---- 範例 ----
if __name__ == "__main__":
    log = LogHelper.get_logger("demo")
    log.verbose("VERBOSE")
    log.debug("DEBUG")
    log.info("INFO")
    log.warning("WARNING")
    log.error("ERROR")
    log.critical("this is CRITICAL")

