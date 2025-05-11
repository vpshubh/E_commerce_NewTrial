from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('checkout/<int:order_id>/', views.checkout_view, name='checkout'),
    path('create-payment-intent/<int:order_id>/', views.create_payment_intent_view, name='create_payment_intent'),
    path('webhook/', views.stripe_webhook, name='webhook'),
    path('success/<int:order_id>/', views.payment_success_view, name='success'),
    path('failure/<int:order_id>/', views.payment_failure_view, name='failure'),
    # Refund URLs
    path('refund/<int:payment_id>/', views.refund_request_view, name='refund_request'),
    path('refund/<int:payment_id>/process/', views.process_refund_view, name='process_refund'),
]