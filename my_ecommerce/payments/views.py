import json
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from orders.models import Order
from .models import Payment, Refund
from .forms import RefundForm
from .stripe_integration import (
    create_payment_intent,
    stripe_webhook as stripe_webhook_handler,
    handle_payment_success,
    handle_payment_failure
)
import logging

logger = logging.getLogger(__name__)


def checkout_view(request, order_id):
    """
    Display checkout page with payment form
    """
    order = get_object_or_404(Order, id=order_id)

    # Check if this order belongs to the current user (if authenticated)
    if request.user.is_authenticated and order.user and order.user != request.user:
        messages.error(request, "You don't have permission to access this order.")
        return redirect('home')

    # Check if order is already paid
    if order.status == 'paid':
        messages.info(request, "This order has already been paid for.")
        return redirect('orders:detail', order_id=order.id)

    context = {
        'order': order,
        'STRIPE_PUBLIC_KEY': settings.STRIPE_PUBLIC_KEY,
    }

    return render(request, 'payments/checkout.html', context)


@require_POST
def create_payment_intent_view(request, order_id):
    """
    Create a payment intent for an order and return the client secret
    """
    order = get_object_or_404(Order, id=order_id)

    # Check if this order belongs to the current user (if authenticated)
    if request.user.is_authenticated and order.user and order.user != request.user:
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    # Create payment intent
    result = create_payment_intent(order, request)

    if result['success']:
        return JsonResponse({
            'success': True,
            'clientSecret': result['clientSecret'],
            'payment_id': result['payment_id']
        })
    else:
        return JsonResponse({
            'success': False,
            'error': result['error']
        }, status=400)


def payment_success_view(request, order_id):
    """
    Handle successful payment redirect
    """
    order = get_object_or_404(Order, id=order_id)

    # Check if this order belongs to the current user (if authenticated)
    if request.user.is_authenticated and order.user and order.user != request.user:
        messages.error(request, "You don't have permission to access this order.")
        return redirect('home')

    # Ensure order is marked as paid (should be done via webhook, but this is a fallback)
    if order.status != 'paid':
        try:
            payment = Payment.objects.filter(order=order).latest('created_at')
            if payment.status == 'completed':
                order.status = 'paid'
                order.save()
        except Payment.DoesNotExist:
            pass

    return render(request, 'payments/success.html', {'order': order})


def payment_failure_view(request, order_id):
    """
    Handle failed payment redirect
    """
    order = get_object_or_404(Order, id=order_id)

    # Check if this order belongs to the current user (if authenticated)
    if request.user.is_authenticated and order.user and order.user != request.user:
        messages.error(request, "You don't have permission to access this order.")
        return redirect('home')

    # Get error message from latest payment if available
    error_message = None
    try:
        payment = Payment.objects.filter(order=order).latest('created_at')
        error_message = payment.error_message
    except Payment.DoesNotExist:
        pass

    return render(request, 'payments/failure.html', {
        'order': order,
        'error_message': error_message
    })


@login_required
def refund_request_view(request, payment_id):
    """
    View for requesting a refund
    """
    payment = get_object_or_404(Payment, id=payment_id)
    order = payment.order

    # Check if this order belongs to the current user
    if order.user != request.user:
        messages.error(request, "You don't have permission to request a refund for this payment.")
        return redirect('home')

    # Check if payment can be refunded
    if not payment.can_be_refunded():
        messages.error(request, "This payment cannot be refunded.")
        return redirect('orders:detail', order_id=order.id)

    if request.method == 'POST':
        form = RefundForm(request.POST, payment=payment)
        if form.is_valid():
            refund = form.save(commit=False)
            refund.payment = payment
            refund.save()

            # Process refund through Stripe in a separate view
            return redirect('payments:process_refund', payment_id=payment.id)
    else:
        form = RefundForm(payment=payment)

    return render(request, 'payments/refund_request.html', {
        'form': form,
        'payment': payment,
        'order': order
    })


@login_required
def process_refund_view(request, payment_id):
    """
    Process a refund through Stripe
    """
    payment = get_object_or_404(Payment, id=payment_id)
    order = payment.order

    # Check if this order belongs to the current user
    if order.user != request.user:
        messages.error(request, "You don't have permission to process a refund for this payment.")
        return redirect('home')

    try:
        # Get the latest refund request
        refund = Refund.objects.filter(payment=payment, status='pending').latest('created_at')

        # Process refund through Stripe
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY

        stripe_refund = stripe.Refund.create(
            payment_intent=payment.payment_intent_id,
            amount=int(refund.amount * 100),  # Convert to cents
        )

        # Update refund status
        refund.refund_id = stripe_refund.id
        refund.status = 'processed'
        refund.save()

        # Update payment status
        payment.status = 'refunded'
        payment.save()

        # Update order status if full refund
        if refund.amount >= payment.amount:
            order.status = 'refunded'
            order.save()

        messages.success(request, "Your refund has been processed successfully.")
        return redirect('orders:detail', order_id=order.id)

    except Refund.DoesNotExist:
        messages.error(request, "No pending refund request found.")
        return redirect('orders:detail', order_id=order.id)
    except stripe.error.StripeError as e:
        messages.error(request, f"Stripe error: {str(e)}")
        return redirect('payments:refund_request', payment_id=payment.id)