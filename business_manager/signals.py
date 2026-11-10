from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Invoice, Transaction


@receiver(post_save, sender=Invoice)
def sync_paid_invoice_transaction(sender, instance, **kwargs):
    if instance.status == "paid":
        Transaction.objects.update_or_create(
            source_invoice=instance,
            defaults={
                "transaction_type": "income",
                "date": instance.paid_date or instance.issue_date,
                "merchant": instance.customer.name,
                "category": "Invoice payment",
                "description": f"Payment for invoice {instance.invoice_number}"[:200],
                "subtotal": instance.final_amount,
                "tax_amount": "0.00",
                "amount": instance.final_amount,
            },
        )
    else:
        Transaction.objects.filter(source_invoice=instance).delete()
