import http.cookies
import logging
from urllib.parse import parse_qs

import jwt
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from accounts.models import User

logger = logging.getLogger(__name__)


def _get_jwt_signing_key() -> str:
    """
    Return the signing key that simplejwt uses for token verification.
    Falls back to SECRET_KEY if SIMPLE_JWT['SIGNING_KEY'] is not configured,
    matching simplejwt's own default behaviour.
    """
    jwt_settings = getattr(settings, 'SIMPLE_JWT', {})
    return jwt_settings.get('SIGNING_KEY', settings.SECRET_KEY)


def _get_jwt_algorithm() -> str:
    """Return the algorithm configured in SIMPLE_JWT (default: HS256)."""
    jwt_settings = getattr(settings, 'SIMPLE_JWT', {})
    return jwt_settings.get('ALGORITHM', 'HS256')


@database_sync_to_async
def get_user(token: str):
    """
    Decode a JWT access token and return the corresponding User.
    Returns AnonymousUser on any validation failure so callers don't
    need to handle exceptions.
    """
    try:
        decoded_data = jwt.decode(
            token,
            _get_jwt_signing_key(),
            algorithms=[_get_jwt_algorithm()],
        )
        user_id = decoded_data.get("user_id")
        return User.objects.get(id=user_id)
    except jwt.ExpiredSignatureError:
        logger.debug("WebSocket JWT token has expired.")
    except jwt.InvalidTokenError as exc:
        logger.debug("WebSocket JWT token is invalid: %s", exc)
    except User.DoesNotExist:
        logger.debug("WebSocket JWT references a non-existent user.")
    return AnonymousUser()


class JWTAuthCookieMiddleware(BaseMiddleware):
    """
    Django Channels middleware that authenticates WebSocket connections
    using a JWT access token stored in the 'access' HTTP cookie.

    Falls back to a 'token' query-string parameter for clients that
    cannot set cookies (e.g. native mobile apps during WS handshake).
    """

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("latin-1")

        token = self._extract_token_from_cookie(cookie_header)

        # Fallback: accept token as a query-string parameter
        if not token:
            query_string = scope.get("query_string", b"").decode()
            query_params = parse_qs(query_string)
            token = query_params.get("token", [None])[0]

        scope["user"] = await get_user(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)

    @staticmethod
    def _extract_token_from_cookie(cookie_header: str):
        """
        Parse the Cookie header using stdlib SimpleCookie so that values
        containing '=' (e.g. base64 padding in JWTs) are handled correctly.
        """
        if not cookie_header:
            return None
        try:
            cookies = http.cookies.SimpleCookie(cookie_header)
            morsel = cookies.get("access")
            return morsel.value if morsel else None
        except http.cookies.CookieError:
            return None
