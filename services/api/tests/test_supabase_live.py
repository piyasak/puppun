"""Live checks against the real Supabase project (opt-in, network).

Run with CLIPFLOW_SUPABASE_URL=https://<ref>.supabase.co. Optionally set
CLIPFLOW_SUPABASE_LIVE_TOKEN to an access token of a real signed-in test user (copied from
the browser session, never committed) plus CLIPFLOW_SUPABASE_LIVE_EMAIL to check it end to end.
"""

from __future__ import annotations

import os

import pytest
from api_test_tokens import mint, new_identity

from clipflow_api.config import Settings
from clipflow_api.identity import InvalidToken, SupabaseVerifier, jwks_resolver

LIVE_URL = os.environ.get("CLIPFLOW_SUPABASE_URL", "")
pytestmark = pytest.mark.skipif(not LIVE_URL, reason="live Supabase check is opt-in (CLIPFLOW_SUPABASE_URL)")


@pytest.fixture(scope="module")
def verifier():
    s = Settings(supabase_url=LIVE_URL)
    return SupabaseVerifier(jwks_resolver(s.supabase_jwks_url), s.supabase_issuer, s.supabase_jwt_audience)


def test_real_project_rejects_a_token_it_did_not_sign(verifier):
    user_id, email = new_identity()
    with pytest.raises(InvalidToken):
        verifier.verify(mint(user_id, email, iss=Settings(supabase_url=LIVE_URL).supabase_issuer))


def test_real_access_token_verifies(verifier):
    token = os.environ.get("CLIPFLOW_SUPABASE_LIVE_TOKEN")
    if not token:
        pytest.skip("no live access token supplied")
    who = verifier.verify(token)
    assert who.email == os.environ.get("CLIPFLOW_SUPABASE_LIVE_EMAIL", who.email).lower()
