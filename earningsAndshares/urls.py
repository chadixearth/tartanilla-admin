# earnings/urls.py
from django.urls import path
from . import views
from .pdf_exports import export_earnings_pdf

urlpatterns = [
    path("earningsAndshares/", views.earningsAndshares, name="earningsAndshares"),
    path("release_payout/<uuid:payout_id>/", views.release_payout, name="release_payout"),
    path("export_earnings_pdf/", export_earnings_pdf, name="export_earnings_pdf"),
]
  