"""Authentication utilities for the transporte API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

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
    """Authenticates requests using a shared static API key header."""

    header_name = "X-API-Key"

    def authenticate(self, request) -> Optional[Tuple[StaticKeyUser, None]]:
        expected_key = getattr(settings, "API_SHARED_SECRET", "")
        if not expected_key:
            # No key configured, skip authentication to allow other strategies.
            return None

        provided_key = request.headers.get(self.header_name)
        if not provided_key:
            raise exceptions.AuthenticationFailed("Missing API key header.")

        if not constant_time_compare(provided_key, expected_key):
            raise exceptions.AuthenticationFailed("Invalid API key.")

        return StaticKeyUser(api_key=provided_key), None
