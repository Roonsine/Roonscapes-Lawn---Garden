import uuid
import datetime
from django.db import models

# Create your models here.
class Customer(models.Model):
    """ Stores contact details for clients requesting quotes or receiving invoices. """
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Quote(models.Model):
    """ Tracks custom estimation requests built by the client on the front-end. """
    STATUS_CHOICES = [
        ('pending','Pending Review'),
        ('converted', 'Converted to Invoice'),
        ('expired', 'Expired/Rejected'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='quotes')
    service_type = models.CharField(max_length=100) # e.g Lawn Mowing, Gardening etc
    estimated_square_footage = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, null=True)
    estimated_total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Quote #{self.id} - {self.customer.name} ({self.service_type})"

class Invoice(models.Model):
    """Represents the official bill sent to clients from your administrative backend."""
    STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='invoices')
    #Link back to the original self-serve quote if it exists; can be blank if manually created.
    originating_quote = models.OneToOneField(Quote, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoice')

    # Automatically creates unique strings like INV-A1B2C3D4
    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    issue_date = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField()
    final_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unpaid')
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        """ Override save method to auto generate a unique invoice number if not present"""
        if not self.invoice_number:
            unique_suffix = uuid.uuid4().hex[:8].upper()
            self.invoice_number = f"INV-{unique_suffix}"

        if not self.due_date:
            self.due_date = datetime.date.today() + datetime.timedelta(days=14)


        super().save(*args, **kwargs)


    def __str__(self):
        return f"{self.invoice_number} - {self.customer.name} (${self.final_amount})"