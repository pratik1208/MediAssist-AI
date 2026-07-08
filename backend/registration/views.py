# from rest_framework.response import Response
from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
import json
from scheduling.ai.handler import handle_patient_message
from core.base_crud_views import BaseCRUDAPIView
from core.models import Conversation, OTPChallenge
from registration.models import InsurancePolicy, IntakeSummary, UploadedDocument
from registration import services

from registration.serializers import (
    InsurancePolicySerializer,
    IntakeSummarySerializer,
    UploadedDocumentSerializer
)


class InsurancePolicyCRUDAPIView(BaseCRUDAPIView):
    model = InsurancePolicy
    serializer_class = InsurancePolicySerializer


class IntakeSummaryCRUDAPIView(BaseCRUDAPIView):
    model = IntakeSummary
    serializer_class = IntakeSummarySerializer


class UploadedDocumentCRUDAPIView(BaseCRUDAPIView):
    model = UploadedDocument
    serializer_class = UploadedDocumentSerializer


# Salt scopes the session token: a token signed here is only accepted by
# registration endpoints that unsign with the same salt.
REGISTRATION_SESSION_SALT = "registration.session"


class StartRegistrationAPIView(APIView):
    """POST /api/registration/start — begin a registration session.

    No auth: a brand-new patient has nothing to log in with yet. Creates a
    Conversation (no patient attached until demographics are collected) and
    returns a signed session token the later registration endpoints require.
    """

    def post(self, request):
        channel = request.data.get("channel", "web")
        valid_channels = {value for value, _ in Conversation.CHANNEL_CHOICES}
        if channel not in valid_channels:
            return Response(
                {"error": f"channel must be one of {sorted(valid_channels)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        conversation = Conversation.objects.create(
            channel=channel,
            started_at=timezone.now(),
            agent_context={
                "active_agent": "registration",
                "registration_stage": "demographics",
            },
        )
        session_token = signing.dumps(
            {"conversation_id": conversation.id}, salt=REGISTRATION_SESSION_SALT
        )
        return Response(
            {"session_token": session_token, "conversation_id": conversation.id},
            status=status.HTTP_201_CREATED,
        )


class RegistrationSessionAPIView(APIView):
    """Base for endpoints that require a session token from /start.

    Clients send the token in an X-Session-Token header. A bad or missing
    token gets a 401 before the endpoint's own code runs.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        token = request.headers.get("X-Session-Token", "")
        try:
            payload = signing.loads(token, salt=REGISTRATION_SESSION_SALT)
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


class SubmitDemographicsAPIView(RegistrationSessionAPIView):
    """POST /api/registration/demographics — create or reuse the patient record.

    Runs duplicate detection first (FR-R3): a returning patient is linked to
    their existing record, and a possible duplicate is never auto-created.
    """

    REQUIRED = ("first_name", "last_name", "dob", "contact_number")

    def post(self, request):
        missing = sorted(f for f in self.REQUIRED if not request.data.get(f))
        if missing:
            return Response(
                {"error": f"missing required fields: {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        full_name = f"{request.data['first_name']} {request.data['last_name']}"
        match, candidates = services.find_matching_patients(
            full_name, request.data["dob"], request.data["contact_number"]
        )
        if match == "possible_duplicate":
            return Response(
                {"match": "possible_duplicate",
                 "detail": "a similar patient exists; staff must resolve before continuing",
                 "candidate_ids": [p.id for p in candidates]},
                status=status.HTTP_409_CONFLICT,
            )

        existing = candidates[0] if match == "existing" else None
        patient = services.create_or_update_patient_record(
            existing, demographics=dict(request.data)
        )
        self.conversation.patient = patient
        self.conversation.save(update_fields=["patient"])
        return Response(
            {"patient_id": patient.id, "match": match},
            status=status.HTTP_200_OK if match == "existing" else status.HTTP_201_CREATED,
        )


class RequestOtpAPIView(RegistrationSessionAPIView):
    """POST /api/registration/otp/request — send a verification code (202)."""

    def post(self, request):
        patient, error = self.patient_or_error()
        if error:
            return error

        channel = request.data.get("channel", "SMS")
        valid_channels = {value for value, _ in OTPChallenge._meta.get_field("channel").choices}
        if channel not in valid_channels:
            return Response(
                {"error": f"channel must be one of {sorted(valid_channels)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if channel == "email" and not patient.email:
            return Response(
                {"error": "patient has no email on file"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        services.create_otp(patient, channel)
        return Response({"detail": "verification code sent"}, status=status.HTTP_202_ACCEPTED)


class VerifyOtpAPIView(RegistrationSessionAPIView):
    """POST /api/registration/otp/verify — {code} -> {verified: true} or 400."""

    ERROR_CODES = {
        "expired": "otp_expired",
        "invalid_code": "otp_invalid",
        "too_many_attempts": "otp_too_many_attempts",
        "no_active_code": "otp_missing",
    }

    def post(self, request):
        patient, error = self.patient_or_error()
        if error:
            return error

        ok, reason = services.verify_otp(patient, str(request.data.get("code", "")))
        if ok:
            if patient.registration_status == "in_process":
                patient.registration_status = "verified"
                patient.save(update_fields=["registration_status"])
            return Response({"verified": True})
        return Response(
            {"verified": False, "code": self.ERROR_CODES[reason]},
            status=status.HTTP_400_BAD_REQUEST,
        )


class UploadDocumentAPIView(RegistrationSessionAPIView):
    """POST /api/registration/documents — multipart {file, doc_type} -> 201.

    Stores the file only; AI extraction fills extracted_data in Phase 4.
    """

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        patient, error = self.patient_or_error()
        if error:
            return error

        upload = request.FILES.get("file")
        doc_type = request.data.get("doc_type", "")
        valid_types = {value for value, _ in UploadedDocument._meta.get_field("document_type").choices}
        if upload is None:
            return Response({"error": "no file provided"}, status=status.HTTP_400_BAD_REQUEST)
        if doc_type not in valid_types:
            return Response(
                {"error": f"doc_type must be one of {sorted(valid_types)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        document = UploadedDocument.objects.create(
            patient=patient, document_type=doc_type, file=upload
        )
        return Response(
            {"id": document.id, "doc_type": document.document_type,
             "extraction_status": document.extraction_status},
            status=status.HTTP_201_CREATED,
        )


class SubmitInsuranceAPIView(RegistrationSessionAPIView):
    """POST /api/registration/insurance — save the policy and check eligibility.

    An inactive policy is flagged in the response but never blocks
    registration (PRD Edge Case 3).
    """

    REQUIRED = ("policy_number", "provider_name", "coverage_start", "coverage_end")
    ALLOWED = REQUIRED + ("member_id", "coverage_details")

    def post(self, request):
        patient, error = self.patient_or_error()
        if error:
            return error

        missing = sorted(f for f in self.REQUIRED if not request.data.get(f))
        if missing:
            return Response(
                {"error": f"missing required fields: {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        insurance = {k: request.data[k] for k in self.ALLOWED if k in request.data}
        insurance.setdefault("coverage_details", "")
        services.create_or_update_patient_record(patient, insurance=insurance)

        policy = InsurancePolicy.objects.get(
            patient=patient, policy_number=insurance["policy_number"]
        )
        result = services.verify_insurance_eligibility(policy)
        return Response(
            {"policy_id": policy.id, "eligibility_status": policy.eligibility_status,
             "flagged": result.status == "ineligible"},
            status=status.HTTP_201_CREATED,
        )


class RegistrationStatusAPIView(RegistrationSessionAPIView):
    """GET /api/registration/status — progress + what's still missing."""

    def get(self, request):
        patient = self.conversation.patient
        if patient is None:
            return Response({
                "registration_status": "in_process",
                "missing": ["demographics", "identity", "insurance", "intake"],
            })

        missing = []
        if not patient.identity_verified:
            missing.append("identity")
        if not InsurancePolicy.objects.filter(patient=patient).exists():
            missing.append("insurance")
        if not IntakeSummary.objects.filter(patient=patient).exists():
            missing.append("intake")
        return Response({
            "registration_status": patient.registration_status,
            "missing": missing,
        })


class CompleteRegistrationAPIView(RegistrationSessionAPIView):
    """POST /api/registration/complete — finish up and emit registration.completed.

    Refused while anything is still missing, so the event downstream agents
    react to can be trusted.
    """

    def post(self, request):
        patient, error = self.patient_or_error()
        if error:
            return error

        missing = []
        if not patient.identity_verified:
            missing.append("identity")
        if not InsurancePolicy.objects.filter(patient=patient).exists():
            missing.append("insurance")
        if not IntakeSummary.objects.filter(patient=patient).exists():
            missing.append("intake")
        if missing:
            return Response(
                {"error": "registration is not finished", "missing": missing},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = services.complete_registration(patient)
        return Response({"registration_status": "complete", "event_id": event.id})


class ChatAPIView(APIView):

    def post(self, request):
        conversation = request.data.get("conversation", [])

        result = handle_patient_message(conversation)

        def event_stream():
            yield f"data: {json.dumps(result, cls=DjangoJSONEncoder)}\n\n"

        return StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
