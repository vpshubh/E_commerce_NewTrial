from django.db import models
from django.utils import timezone
from orders.models import Order


class Payment(models.Model):
    """
    Payment model to track all payment transactions
    """
    PAYMENT_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    )

    PAYMENT_METHOD_CHOICES = (
        ('credit_card', 'Credit Card'),
        ('debit_card', 'Debit Card'),
        ('paypal', 'PayPal'),
        ('apple_pay', 'Apple Pay'),
        ('google_pay', 'Google Pay'),
    )

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    transaction_id = models.CharField(max_length=255, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True, null=True)
    last_four = models.CharField(max_length=4, blank=True, null=True, help_text="Last four digits of the card")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    error_message = models.TextField(blank=True, null=True)
    refund_reason = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.id} - {self.order.order_number} - {self.status}"

    def is_successful(self):
        return self.status == 'completed'

    def is_refunded(self):
        return self.status == 'refunded'

    def can_be_refunded(self):
        return self.is_successful() and not self.is_refunded()

    def get_formatted_amount(self):
        return f"${self.amount}"


class Refund(models.Model):
    """
    Refund model to track refund transactions
    """
    REFUND_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    )

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='refunds')
    refund_id = models.CharField(max_length=255, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=REFUND_STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Refund {self.id} - {self.payment.order.order_number}"