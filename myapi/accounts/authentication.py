from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import CSRFCheck
from rest_framework import exceptions


class CookieJWTAuthentication(JWTAuthentication):
    """
    Extension of JWTAuthentication that looks for the token inside the 
    HttpOnly `access` cookie and enforces CSRF protection.
    """

    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
        else:
            raw_token = request.COOKIES.get("access")

        if raw_token is None:
            return None

        # Enforce CSRF if using cookies
        if header is None:
            self.enforce_csrf(request)

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token

    def enforce_csrf(self, request):
        """
        Enforce CSRF validation for cookie-based authentication.
        """
        check = CSRFCheck(request)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f'CSRF Failed: {reason}')

