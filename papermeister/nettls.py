"""TLS verification against the OS trust store, for networks that inspect TLS.

An institution that inspects TLS re-signs every connection with its own root CA
(KOPRI's does). That CA lives in the OS trust store — the browser and the Zotero
client are perfectly happy — but httpx and requests verify against certifi's
bundle, which has never heard of it, so every call to api.zotero.org dies with
``CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain``.

``truststore`` points verification at the OS store instead, which is the one
place the institutional CA actually is. It replaces an older workaround that
monkey-patched ``requests.api.request`` to default ``verify=False``: that turned
verification off for every host rather than trusting one more CA, and it had
quietly stopped working anyway — pyzotero 1.13 moved from requests to httpx, so
the patch no longer sat on the path Zotero calls take.

``inject_into_ssl()`` is process-global and only affects contexts created after
it runs, so entry points call this before anything opens a connection — not
lazily at the call site.
"""

import logging

logger = logging.getLogger(__name__)

try:
    import truststore
except ImportError:  # optional: without it we simply keep certifi's bundle
    truststore = None  # type: ignore[assignment]

_installed = False


def install_system_trust() -> bool:
    """Verify TLS against the OS trust store. Idempotent; True if in effect.

    Never raises: on a network that doesn't inspect TLS, certifi works fine and
    a missing or unhappy truststore is not a reason to refuse to start.
    """
    global _installed
    if _installed:
        return True
    if truststore is None:
        logger.debug('truststore is not installed; TLS keeps using certifi')
        return False
    try:
        truststore.inject_into_ssl()
    except Exception:  # pragma: no cover - platform-specific, non-fatal
        logger.warning('could not use the OS trust store', exc_info=True)
        return False
    _installed = True
    logger.debug('TLS now verifies against the OS trust store')
    return True
