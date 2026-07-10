"""Signed session tokens for patient-facing flow endpoints.

/api/registration/start issues the token (a signed conversation id); every
patient-facing endpoint in any agent verifies it here. Lives in core because
agents never import each other (SPEC_Core §2) — registration, triage, and
later agents all share this one door.

The salt value predates this module (tokens were first issued by
registration) and must not change, or every session in flight breaks.
"""

from django.core import signing
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from core.models import Conversation

SESSION_SALT = "registration.session"


class SessionTokenAPIView(APIView):
    """Base for endpoints that require a session token from /start.

    Clients send the token in an X-Session-Token header. A bad or missing
    token is rejected before the endpoint's own code runs.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        token = request.headers.get("X-Session-Token", "")
        try:
            payload = signing.loads(token, salt=SESSION_SALT)
            self.conversation = Conversation.objects.get(id=payload["conversation_id"])
        except (signing.BadSignature, Conversation.DoesNotExist):
            raise AuthenticationFailed("missing or invalid session token")

    def patient_or_error(self):
        """The session's patient, or a 400 telling the client what to do first."""
        if self.conversation.patient is None:
            return None, Response(
                {"error": "submit demographics before this step"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self.conversation.patient, None

    def verified_patient_or_error(self):
        """The session's identity-verified patient, or the blocking 400/403."""
        patient, error = self.patient_or_error()
        if error:
            return None, error
        if not patient.identity_verified:
            return None, Response(
                {"error": "identity verification required before this step"},
                status=status.HTTP_403_FORBIDDEN,
            )
        return patient, None
