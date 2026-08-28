from django.urls import path
from rest_framework.routers import DefaultRouter

from .views.dashboard import DashboardViewSet
from .views.reports import ReportViewSet
from .views.search import SearchView

router = DefaultRouter()
router.include_format_suffixes = False
router.register("dashboard", DashboardViewSet, basename="dashboard")
router.register("reports", ReportViewSet, basename="report")

urlpatterns = router.urls + [
    path("search/", SearchView.as_view(), name="search"),
]
