from django import forms
from .models import Payment, Refund


class PaymentMethodForm(forms.Form):
    """
    Form for selecting payment method
    """
    PAYMENT_METHOD_CHOICES = Payment.PAYMENT_METHOD_CHOICES

    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHOD_CHOICES,
        widget=forms.RadioSelect,
        required=True
    )

    save_payment_method = forms.BooleanField(
        required=False,
        label="Save this payment method for future purchases"
    )


class CreditCardForm(forms.Form):
    """
    Form for credit card details - Note that actual card data should not be processed
    through Django but directly via Stripe.js on the frontend
    """
    name_on_card = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'placeholder': 'Name on Card',
            'class': 'form-control'
        })
    )

    # These fields are for display only - actual card processing will be done via Stripe.js
    # No sensitive card data should ever touch our server
    card_element = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )


class RefundForm(forms.ModelForm):
    """
    Form for processing refunds
    """

    class Meta:
        model = Refund
        fields = ['amount', 'reason']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        payment = kwargs.pop('payment', None)
        super().__init__(*args, **kwargs)

        if payment:
            self.fields['amount'].initial = payment.amount
            self.fields['amount'].widget.attrs['max'] = payment.amount