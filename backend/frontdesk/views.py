"""Front-desk API layer (Agent 9, Phase 3).

Patient-facing: /api/frontdesk/start issues the same signed session token
every other patient flow uses (core.sessions — one door), and
/api/frontdesk/chat is THE single omnichannel entry point (SSE streaming,
same shape as Agent 1's chat). Free text goes through the Phase 4 AI
router (red-flag screened first, multi-intent); an explicit intent or auth
action skips the model and dispatches deterministically — same envelope
either way.

Staff-facing: the "human needed" queue — list, claim, resolve (FR-A7),
mirroring triage's escalation endpoints.

Every chat turn writes Message rows on the conversation, so the audit
trail (FR-A8) exists from Phase 3 onward. Auth turns log a placeholder
instead of the submitted DOB/OTP — verification secrets don't belong in a
transcript.
"""

import json

from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Avg, Case, Count, F, IntegerField, Value, When
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.base_crud_views import BaseCRUDAPIView
from core.models import Conversation, Message
from core.sessions import SESSION_SALT, SessionTokenAPIView
from frontdesk import services
from frontdesk.models import IntentRoute, KnowledgeArticle, PatientSession, StaffTask
from frontdesk.serializers import KnowledgeArticleSerializer, StaffTaskSerializer


class StartFrontdeskAPIView(APIView):
    """POST /api/frontdesk/start — open a front-door session.

    No auth: the session starts anonymous (FR-A3) and steps up inside the
    chat when a protected intent appears. Creates the Conversation + its
    PatientSession and returns the signed session token.
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
            agent_context={"active_agent": "frontdesk"},
        )
        session = PatientSession.objects.create(conversation=conversation, channel=channel)
        session_token = signing.dumps(
            {"conversation_id": conversation.id}, salt=SESSION_SALT
        )
        return Response(
            {"session_token": session_token, "conversation_id": conversation.id,
             "session_id": session.id},
            status=status.HTTP_201_CREATED,
        )


class FrontdeskChatAPIView(SessionTokenAPIView):
    """POST /api/frontdesk/chat — the single omnichannel entry point.

    Four request shapes, one SSE response envelope:
      {"action": "start_auth", "contact_number": ..., "dob": ...}
      {"action": "verify_otp", "dob": ..., "otp": ...}
      {"intent": ..., "payload": {...}}          (explicit, deterministic)
      {"message": "refill my BP meds and ..."}   (free text -> the Phase 4
        AI router, red-flag screened first, multi-intent)

    The final SSE event always carries {"done": true, "status": ..., "reply": ...}.
    """

    HISTORY_TURNS = 10

    def _history(self):
        """Recent patient/assistant turns, oldest first, for router context."""
        rows = (Message.objects
                .filter(conversation=self.conversation, role__in=["Patient", "Assistant"])
                .order_by("-id")[:self.HISTORY_TURNS])
        return [{"role": "user" if m.role == "Patient" else "assistant",
                 "content": m.content} for m in reversed(rows)]

    def post(self, request):
        # Any signed session can walk in the front door — one issued by
        # /frontdesk/start or by another flow (same token machinery).
        session, _ = PatientSession.objects.get_or_create(
            conversation=self.conversation,
            defaults={"channel": self.conversation.channel},
        )
        action = request.data.get("action")
        intent = request.data.get("intent")
        text = (request.data.get("message") or "").strip()

        if action == "start_auth":
            contact_number = (request.data.get("contact_number") or "").strip()
            dob = request.data.get("dob")
            if not contact_number or not dob:
                return Response({"error": "contact_number and dob are required"},
                                status=status.HTTP_400_BAD_REQUEST)
            result = services.start_authentication(session, contact_number, dob)
            outcome = {"status": "auth_started" if result["ok"] else "auth_failed",
                       "reply": result["message"]}
            patient_line = "[identity claim submitted]"

        elif action == "verify_otp":
            dob = request.data.get("dob")
            otp = (request.data.get("otp") or "").strip()
            if not dob or not otp:
                return Response({"error": "dob and otp are required"},
                                status=status.HTTP_400_BAD_REQUEST)
            result = services.authenticate_session(session, dob, otp)
            if result["ok"]:
                resumed = services.resume_pending_intents(session)
                outcome = {"status": "authenticated", "reply": result["message"],
                           "resumed": resumed}
            else:
                outcome = {"status": "auth_failed", "reply": result["message"]}
            patient_line = "[verification code submitted]"

        elif intent:
            payload = request.data.get("payload") or ({"text": text} if text else {})
            outcome = services.dispatch_intent(session, intent, payload)
            patient_line = text or f"[{intent} request]"

        elif text:
            from frontdesk.ai import handle_frontdesk_message
            outcome = handle_frontdesk_message(session, text, history=self._history())
            patient_line = text

        else:
            return Response(
                {"error": "provide a message, an intent, or an action "
                          "(start_auth / verify_otp)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        Message.objects.create(conversation=self.conversation, role="Patient",
                               content=patient_line)
        Message.objects.create(conversation=self.conversation, role="Assistant",
                               content=outcome.get("reply", ""))

        def event_stream():
            yield f"data: {json.dumps({'done': True, **outcome}, cls=DjangoJSONEncoder)}\n\n"

        return StreamingHttpResponse(event_stream(), content_type="text/event-stream")


# -- FR-A7: the staff task queue -----------------------------------------------------

# Queue order: severity first, then oldest waiting.
_PRIORITY_RANK = Case(
    When(priority="critical", then=Value(0)),
    When(priority="high", then=Value(1)),
    default=Value(2),
    output_field=IntegerField(),
)


def _task_row(task: StaffTask) -> dict:
    return {
        "id": task.id,
        "category": task.category,
        "priority": task.priority,
        "status": task.status,
        "summary": task.summary,
        "patient_id": task.patient_id,
        "patient_name": (f"{task.patient.first_name} {task.patient.last_name}"
                         if task.patient else None),
        "session_id": task.session_id,
        "claimed_by": task.claimed_by,
        "resolved_at": task.resolved_at,
        "created_at": task.created_at,
    }


class StaffTaskQueueAPIView(APIView):
    """GET /api/staff/frontdesk/tasks/?status=open&category=... — the queue."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        tasks = (StaffTask.objects.select_related("patient")
                 .annotate(_rank=_PRIORITY_RANK)
                 .order_by("_rank", "created_at"))
        status_filter = request.query_params.get("status")
        if status_filter:
            tasks = tasks.filter(status=status_filter)
        category = request.query_params.get("category")
        if category:
            tasks = tasks.filter(category=category)
        return Response([_task_row(t) for t in tasks])


class StaffTaskClaimAPIView(APIView):
    """POST /api/staff/frontdesk/tasks/{id}/claim/ — take a task off the queue."""

    permission_classes = [IsAdminUser]

    def post(self, request, task_id):
        try:
            task = StaffTask.objects.get(id=task_id)
        except StaffTask.DoesNotExist:
            return Response({"error": "task not found"}, status=status.HTTP_404_NOT_FOUND)
        if task.status != "open":
            return Response({"error": f"task is {task.status}, not open"},
                            status=status.HTTP_409_CONFLICT)
        task.status = "claimed"
        task.claimed_by = request.data.get("claimed_by") or request.user.get_username()
        task.save(update_fields=["status", "claimed_by"])
        return Response(_task_row(task))


class StaffTaskResolveAPIView(APIView):
    """POST /api/staff/frontdesk/tasks/{id}/resolve/ — close a task out."""

    permission_classes = [IsAdminUser]

    def post(self, request, task_id):
        try:
            task = StaffTask.objects.get(id=task_id)
        except StaffTask.DoesNotExist:
            return Response({"error": "task not found"}, status=status.HTTP_404_NOT_FOUND)
        if task.status == "resolved":
            return Response({"error": "task is already resolved"},
                            status=status.HTTP_409_CONFLICT)
        task.status = "resolved"
        task.resolved_at = timezone.now()
        if not task.claimed_by:  # resolving straight from open still records who
            task.claimed_by = request.data.get("claimed_by") or request.user.get_username()
        task.save(update_fields=["status", "resolved_at", "claimed_by"])
        return Response(_task_row(task))


class FrontdeskAnalyticsAPIView(APIView):
    """GET /api/staff/frontdesk/analytics/ — FR-A9 aggregates (staff only).

    "Resolved with zero staff tasks" is exactly IntentRoute.status ==
    "completed" (dispatch_intent sets "escalated" precisely when a handler
    created a StaffTask), so automation/escalation rate falls straight out
    of the audit trail Phase 3 already writes. Nothing on Message carries a
    timestamp, and an automated dispatch finishes inside the same request
    it started in — so the only response-time gap this schema can honestly
    measure is how long an escalated task waited on a human
    (StaffTask.created_at -> resolved_at), not end-to-end patient latency.
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        routes = IntentRoute.objects.all()
        total = routes.count()
        completed = routes.filter(status="completed").count()
        escalated = routes.filter(status="escalated").count()

        def rate(part, whole):
            return round(part / whole, 3) if whole else None

        top_types = routes.values("intent").annotate(n=Count("id")).order_by("-n")[:5]

        resolved = StaffTask.objects.exclude(resolved_at=None)
        avg_response = resolved.aggregate(avg=Avg(F("resolved_at") - F("created_at")))["avg"]

        return Response({
            "volume": {
                "sessions": PatientSession.objects.count(),
                "intents_routed": total,
            },
            "automation": {
                "completed": completed,
                "escalated": escalated,
                "automation_rate": rate(completed, total),
                "escalation_rate": rate(escalated, total),
            },
            "avg_staff_response_seconds": (
                round(avg_response.total_seconds(), 1) if avg_response else None
            ),
            "top_request_types": [
                {"intent": row["intent"], "count": row["n"]} for row in top_types
            ],
        })


# -- generic CRUD (dev/admin convenience) ---------------------------------------------
# No CRUD for PatientSession/IntentRoute on purpose: those are conversation
# state written only through the chat flow — a write endpoint would bypass
# the auth gate.

class KnowledgeArticleCRUDAPIView(BaseCRUDAPIView):
    model = KnowledgeArticle
    serializer_class = KnowledgeArticleSerializer

    @staticmethod
    def _refresh_vector(article_id):
        from django.contrib.postgres.search import SearchVector
        KnowledgeArticle.objects.filter(id=article_id).update(
            search_vector=SearchVector("title", weight="A")
            + SearchVector("body", weight="B")
        )

    def post(self, request, id=None):
        response = super().post(request, id)
        if response.status_code == 201:
            self._refresh_vector(response.data["id"])
        return response

    def patch(self, request, id=None):
        response = super().patch(request, id)
        if response.status_code == 200:
            self._refresh_vector(id)
        return response


class StaffTaskCRUDAPIView(BaseCRUDAPIView):
    model = StaffTask
    serializer_class = StaffTaskSerializer
