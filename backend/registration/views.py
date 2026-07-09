# from rest_framework.response import Response
from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
import json
from core.ai import stream_reply
from core.base_crud_views import BaseCRUDAPIView
from core.models import Conversation, Message, OTPChallenge, Patient
from registration.ai.handler import handle_registration_message
from registration.ai.prompts import REGISTRATION_SYSTEM_PROMPT
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
            # Record the hold on the conversation, matching what the chat
            # handler does — the chat state gate and the duplicates_prevented
            # analytics both read duplicate_candidate_ids from agent_context.
            ctx = self.conversation.agent_context or {}
            ctx["duplicate_candidate_ids"] = [p.id for p in candidates]
            ctx["registration_stage"] = "duplicate_hold"
            self.conversation.agent_context = ctx
            self.conversation.save(update_fields=["agent_context"])
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

        # Channel choices are stored as e.g. "SMS"/"email"; accept any casing.
        by_lower = {value.lower(): value
                    for value, _ in OTPChallenge._meta.get_field("channel").choices}
        channel = by_lower.get(str(request.data.get("channel", "SMS")).lower())
        if channel is None:
            return Response(
                {"error": f"channel must be one of {sorted(by_lower.values())}"},
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


# What the assistant's next visible message should do, per stage. The stage
# comes from the state gate in handle_registration_message — the model never
# decides it.
STAGE_REPLY_GUIDANCE = {
    "demographics": "Continue collecting demographics. Ask exactly ONE question, about: {topic}.",
    "duplicate_hold": "Tell the patient a very similar record already exists and a staff member "
                      "will review it before their registration continues. Do not re-ask their details.",
    "identity_verification": "Tell the patient a 6-digit verification code is being sent to their "
                             "phone, and ask them to type it into the code box shown on screen.",
    "insurance": "Ask the patient to upload a photo of their insurance card with the upload button, "
                 "or to tell you their provider name and policy number.",
    "intake": "Continue the medical intake. Ask exactly ONE question, about: {topic}.",
    "done": "Tell the patient their registration is complete and a clinician will review their "
            "information. Offer to help book an appointment next.",
}


# Demographic fields the chat model should treat as already collected when
# they exist on the patient record (they may have arrived via the REST
# endpoints rather than the chat itself).
ON_FILE_FIELDS = (
    ("first_name", "first name"),
    ("last_name", "last name"),
    ("dob", "date of birth"),
    ("contact_number", "phone number"),
    ("email", "email address"),
    ("address", "home address"),
    ("emergency_contact", "emergency contact"),
    ("preferred_language", "preferred language"),
    ("preferred_pharmacy", "preferred pharmacy"),
)


def on_file_context(conversation):
    """A context message telling the model what the clinic already has.

    Data can enter through the REST endpoints (demographics form, insurance
    upload) and is then invisible in the chat history — without this note the
    model re-asks for it and never considers the demographics collected.
    Returned as the first history message, or None when nothing is on file.
    """
    patient = conversation.patient
    if patient is None:
        return None
    on_file = [label for field, label in ON_FILE_FIELDS if getattr(patient, field, None)]
    if patient.identity_verified:
        on_file.append("verified identity")
    if InsurancePolicy.objects.filter(patient=patient).exists():
        on_file.append("insurance policy")
    note = (
        "[Clinic system note — this is context, not the patient speaking. "
        f"The patient's name on file is {patient.first_name}. The clinic "
        "already has the following on file; treat them as collected, never "
        f"re-ask for them: {', '.join(on_file)}.]"
    )
    return {"role": "user", "content": note}


class RegistrationChatAPIView(RegistrationSessionAPIView):
    """POST /api/registration/chat — {message} -> SSE stream (spec API table).

    Two model calls per turn: handle_registration_message extracts data and
    picks the stage, then stream_reply writes the patient-visible answer,
    streamed as SSE. The final SSE event carries stage/ui_hints so the
    frontend can show the OTP box or upload button.
    """

    def post(self, request):
        text = (request.data.get("message") or "").strip()
        if not text:
            return Response({"error": "message is required"}, status=status.HTTP_400_BAD_REQUEST)

        conversation = self.conversation
        Message.objects.create(conversation=conversation, role="Patient", content=text)
        history = [
            {"role": "user" if m.role == "Patient" else "assistant", "content": m.content}
            for m in Message.objects.filter(
                conversation=conversation, role__in=["Patient", "Assistant"]
            ).order_by("id")
        ]
        # Rebuilt fresh each turn (never persisted as a Message), so it always
        # reflects the current record.
        context_note = on_file_context(conversation)
        if context_note:
            history.insert(0, context_note)

        result = handle_registration_message(conversation, history)
        topic = result.get("next_question_topic") or "whatever is still missing"
        guidance = STAGE_REPLY_GUIDANCE[result["stage"]].format(topic=topic)

        def event_stream():
            parts = []
            for delta in stream_reply(
                system=REGISTRATION_SYSTEM_PROMPT
                + "\n\nInstruction for your next message: " + guidance,
                messages=history,
            ):
                parts.append(delta)
                yield f"data: {json.dumps({'delta': delta})}\n\n"
            Message.objects.create(
                conversation=conversation, role="Assistant", content="".join(parts)
            )
            meta = {key: result[key] for key in
                    ("stage", "ui_hints", "registration_complete", "patient_id")}
            yield f"data: {json.dumps({'done': True, **meta}, cls=DjangoJSONEncoder)}\n\n"

        return StreamingHttpResponse(event_stream(), content_type="text/event-stream")


class RegistrationAnalyticsAPIView(APIView):
    """GET /api/staff/registration/analytics — FR-R10 aggregates (staff only)."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        total = Patient.objects.count()
        completed = Patient.objects.filter(registration_status="complete").count()
        otp_total = OTPChallenge.objects.count()
        otp_verified = OTPChallenge.objects.filter(consumed_at__isnull=False).count()

        def rate(part, whole):
            return round(part / whole, 3) if whole else None

        return Response({
            "patients": {
                "total": total,
                "completed": completed,
                "completion_rate": rate(completed, total),
                "identity_verified": Patient.objects.filter(identity_verified=True).count(),
            },
            "otp": {
                "challenges_sent": otp_total,
                "verified": otp_verified,
                "verification_success_rate": rate(otp_verified, otp_total),
            },
            "duplicates_prevented": Conversation.objects.filter(
                agent_context__has_key="duplicate_candidate_ids"
            ).count(),
            "insurance": {
                "policies": InsurancePolicy.objects.count(),
                "ineligible_flagged": InsurancePolicy.objects.filter(
                    eligibility_status="ineligible"
                ).count(),
            },
            "documents": {
                "uploaded": UploadedDocument.objects.count(),
                "extracted": UploadedDocument.objects.filter(extraction_status="done").count(),
            },
        })
