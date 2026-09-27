from django.urls import path
from . import views

urlpatterns = [
    path("hello/",      views.HelloView.as_view()),
    path("bundle/",     views.BundleView.as_view()),
    path("directory/",  views.DirectoryView.as_view()),
    path("attendance/", views.AttendanceUploadView.as_view()),
    path("enroll/",     views.EnrollView.as_view()),
]
