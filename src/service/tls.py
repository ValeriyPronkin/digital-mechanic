"""TLS для российских сервисов (GigaChat и др.): доверять корневому сертификату Минцифры вместе с обычными.

Сервер GigaChat подписан Russian Trusted Root CA, которому Python и macOS по умолчанию не доверяют —
без этого модуля запрос падает с `CERTIFICATE_VERIFY_FAILED` ещё до проверки ключа.

    import httpx
    from service.tls import ssl_context, RU_ROOT_CA

    httpx.Client(verify=ssl_context())                              # любой HTTP-клиент на httpx
    openai.OpenAI(base_url=..., http_client=httpx.Client(verify=ssl_context()))
    GigaChat(credentials=..., ca_bundle_file=str(RU_ROOT_CA))       # SDK gigachat

`verify=False` не использовать: это отключает проверку сервера целиком.
"""

from __future__ import annotations

import ssl
from functools import cache
from pathlib import Path

# Публичный корневой сертификат Минцифры, источник — https://www.gosuslugi.ru/crt (действует до 27.02.2032).
RU_ROOT_CA = Path(__file__).parent / "certs" / "russian_trusted_root_ca.pem"
# SHA-256 отпечаток (DER) — сверяется тестом, чтобы файл не подменили.
RU_ROOT_CA_SHA256 = "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"


@cache
def ssl_context() -> ssl.SSLContext:
    """Обычные корневые сертификаты (certifi, если установлен; иначе системные) + Russian Trusted Root CA."""
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=str(RU_ROOT_CA))
    return ctx
