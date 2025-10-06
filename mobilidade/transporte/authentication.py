"""Authentication utilities for the transporte API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from django.conf import settings
from django.utils.crypto import constant_time_compare
from rest_framework import authentication, exceptions


@dataclass(frozen=True)
class StaticKeyUser:
    """Minimal user representation for static API key authentication."""

    api_key: str

    @property
    def is_authenticated(self) -> bool:  # pragma: no cover - property
        return True

    @property
    def is_anonymous(self) -> bool:  # pragma: no cover - property
        return False

    def __str__(self) -> str:
        return "StaticKeyUser"


class StaticKeyAuthentication(authentication.BaseAuthentication):
    """Authenticates requests using one of the configured static API keys."""

    header_name = "X-API-Key"

    def _expected_keys(self) -> Iterable[str]:
        secrets = getattr(settings, "API_SHARED_SECRETS", None)
        if secrets:
            yield from secrets
        single_secret = getattr(settings, "API_SHARED_SECRET", "")
        if single_secret:
            yield single_secret

    def authenticate(self, request) -> Optional[Tuple[StaticKeyUser, None]]:
        expected_keys = list(dict.fromkeys(self._expected_keys()))
        if not expected_keys:
            # No key configured, skip authentication to allow other strategies.
            return None

        provided_key = request.headers.get(self.header_name)
        if not provided_key:
            return None

        for expected_key in expected_keys:
            if constant_time_compare(provided_key, expected_key):
                return StaticKeyUser(api_key=provided_key), None

        raise exceptions.AuthenticationFailed("Invalid API key.")
