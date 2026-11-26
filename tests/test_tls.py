"""Сертификат Минцифры на месте, не подменён и попадает в TLS-контекст (нужен для GigaChat)."""

import hashlib
import ssl

from service.tls import RU_ROOT_CA, RU_ROOT_CA_SHA256, ssl_context


def test_ru_root_ca_fingerprint() -> None:
    der = ssl.PEM_cert_to_DER_cert(RU_ROOT_CA.read_text(encoding="ascii"))
    assert hashlib.sha256(der).hexdigest() == RU_ROOT_CA_SHA256


def test_ssl_context_trusts_ru_root_and_keeps_verification() -> None:
    ctx = ssl_context()
    subjects = [str(cert.get("subject")) for cert in ctx.get_ca_certs()]
    assert any("Russian Trusted Root CA" in s for s in subjects)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname
