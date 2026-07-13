from django.urls import path

from frontdesk.views import (
    FrontdeskChatAPIView,
    KnowledgeArticleCRUDAPIView,
    StaffTaskClaimAPIView,
    StaffTaskCRUDAPIView,
    StaffTaskQueueAPIView,
    StaffTaskResolveAPIView,
    StartFrontdeskAPIView,
)

urlpatterns = [
    # patient-facing front door
    path("frontdesk/start", StartFrontdeskAPIView.as_view()),
    path("frontdesk/chat", FrontdeskChatAPIView.as_view()),
    # staff task queue (FR-A7)
    path("staff/frontdesk/tasks/", StaffTaskQueueAPIView.as_view()),
    path("staff/frontdesk/tasks/<int:task_id>/claim/", StaffTaskClaimAPIView.as_view()),
    path("staff/frontdesk/tasks/<int:task_id>/resolve/", StaffTaskResolveAPIView.as_view()),
    # generic CRUD (dev/admin convenience)
    path("knowledgearticle", KnowledgeArticleCRUDAPIView.as_view()),
    path("knowledgearticle/<int:id>", KnowledgeArticleCRUDAPIView.as_view()),
    path("stafftask", StaffTaskCRUDAPIView.as_view()),
    path("stafftask/<int:id>", StaffTaskCRUDAPIView.as_view()),
]
