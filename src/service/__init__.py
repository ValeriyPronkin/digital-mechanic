"""Сервис хакатона."""

import time
import uuid

__version__ = "0.1.0"
# Экземпляр процесса: для разбора холодных стартов стенда (/health → instance).
INSTANCE_ID = uuid.uuid4().hex[:8]
IMPORT_STARTED = time.monotonic()
