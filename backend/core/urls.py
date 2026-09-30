from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views, auth_views, reports, account

router = DefaultRouter()
router.register("students",   views.StudentViewSet)
router.register("cards",      views.CardViewSet)
router.register("venues",     views.VenueViewSet)
router.register("courses",    views.CourseViewSet)
router.register("enrollments", views.EnrollmentViewSet)
router.register("devices",    views.DeviceViewSet)
router.register("slots",      views.TimetableSlotViewSet)
router.register("sessions",   views.ClassSessionViewSet)
router.register("taps",       views.TapEventViewSet)
router.register("attendance", views.AttendanceRecordViewSet)
router.register("audit",      views.AuditLogViewSet)
router.register("members",    auth_views.MembershipViewSet,
                basename="membership")
router.register("invitations", auth_views.InvitationViewSet,
                basename="invitation")

urlpatterns = [
    path("me/",           auth_views.MeView.as_view()),
    path("me/profile/",   account.ProfileView.as_view()),
    path("me/password/",  account.ChangePasswordView.as_view()),
    path("organization/", auth_views.OrganizationView.as_view()),
    path("reports/overview/", reports.OverviewReport.as_view()),
    path("reports/recheck/", reports.RecheckTaps.as_view()),
    path("reports/course/<int:pk>/", reports.CourseReport.as_view()),
    path("", include(router.urls)),
]
