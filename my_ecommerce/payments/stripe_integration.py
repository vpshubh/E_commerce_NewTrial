import stripe
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import redirect, get_object_or_404
from orders.models import Order
from .models import Payment
from django.urls import reverse
import logging

# Configure Stripe API key
stripe.api_key = settings.STRIPE_SECRET_KEY
endpoint_secret = settings.STRIPE_WEBHOOK_SECRET
logger = logging.getLogger(__name__)


def create_payment_intent(order, request=None):
    """
    Create a Stripe Payment Intent for an order
    """
    try:
        # Calculate the total in cents
        amount_cents = int(order.get_total() * 100)

        # Metadata to associate the payment with the order
        metadata = {
            'order_number': order.order_number,
            'user_id': str(order.user.id) if order.user else 'guest',
        }

        # Create a payment intent
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency='usd',
            metadata=metadata,
            description=f"Payment for Order #{order.order_number}",
        )

        # Create or update payment record
        payment, created = Payment.objects.update_or_create(
            order=order,
            defaults={
                'payment_intent_id': intent.id,
                'amount': order.get_total(),
                'status': 'pending'
            }
        )

        return {
            'clientSecret': intent.client_secret,
            'payment_id': payment.id,
            'success': True
        }

    except Exception as e:
        logger.error(f"Error creating payment intent: {str(e)}")
        return {
            'error': str(e),
            'success': False
        }


def handle_payment_success(payment_intent):
    """
    Handle successful payment
    """
    # Get the order from the metadata
    order_number = payment_intent['metadata']['order_number']
    try:
        order = Order.objects.get(order_number=order_number)

        # Update order status
        order.status = 'paid'
        order.save()

        # Update payment record
        payment = Payment.objects.get(payment_intent_id=payment_intent['id'])
        payment.status = 'completed'
        payment.transaction_id = payment_intent['id']
        payment.save()

        # Update inventory (reduce stock)
        for item in order.items.all():
            product = item.product
            product.stock -= item.quantity
            product.save()

        # Send confirmation email
        # send_order_confirmation_email(order)

        return True, order
    except Order.DoesNotExist:
        logger.error(f"Order {order_number} not found")
        return False, None
    except Exception as e:
        logger.error(f"Error handling successful payment: {str(e)}")
        return False, None


def handle_payment_failure(payment_intent):
    """
    Handle failed payment
    """
    # Get the order from the metadata
    order_number = payment_intent['metadata']['order_number']
    try:
        order = Order.objects.get(order_number=order_number)

        # Update order status
        order.status = 'payment_failed'
        order.save()

        # Update payment record
        payment = Payment.objects.get(payment_intent_id=payment_intent['id'])
        payment.status = 'failed'
        payment.save()

        # Log the failure reason if available
        if 'last_payment_error' in payment_intent and payment_intent['last_payment_error']:
            logger.error(f"Payment failed: {payment_intent['last_payment_error']['message']}")

        return True, order
    except Order.DoesNotExist:
        logger.error(f"Order {order_number} not found")
        return False, None
    except Exception as e:
        logger.error(f"Error handling failed payment: {str(e)}")
        return False, None


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """
    Handle Stripe webhooks
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        # Invalid payload
        logger.error(f"Invalid webhook payload: {str(e)}")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        logger.error(f"Invalid webhook signature: {str(e)}")
        return HttpResponse(status=400)

    # Handle the event
    if event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        success, order = handle_payment_success(payment_intent)
        if not success:
            return HttpResponse(status=500)

    elif event['type'] == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        success, order = handle_payment_failure(payment_intent)
        if not success:
            return HttpResponse(status=500)

    # Return a 200 response to acknowledge receipt of the event
    return HttpResponse(status=200)


def payment_success_view(request, order_id):
    """
    View for successful payment redirect
    """
    order = get_object_or_404(Order, id=order_id)
    return render(request, 'payments/success.html', {'order': order})


def payment_failure_view(request, order_id):
    """
    View for failed payment redirect
    """
    order = get_object_or_404(Order, id=order_id)
    return render(request, 'payments/failure.html', {'order': order})