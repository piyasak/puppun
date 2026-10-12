"""HTTPS roots for the Agent (2026-10-12): certifi's roots are added, verification stays on."""

import ssl

import certifi

from agent import net


def test_context_verifies_and_adds_certifis_roots():
    ctx = net.context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    only_certifi = ssl.create_default_context(cafile=certifi.where())
    assert ctx.cert_store_stats()["x509_ca"] >= only_certifi.cert_store_stats()["x509_ca"] > 100
