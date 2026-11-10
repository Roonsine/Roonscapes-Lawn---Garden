import uuid
import datetime
import io
import math
from decimal import Decimal
from django.db import models
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.core.mail import EmailMessage
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from django.utils import timezone
from django.utils.deconstruct import deconstructible

from .storage import PrivateReceiptStorage


@deconstructible
class ReceiptSizeValidator:
    limit = 10 * 1024 * 1024

    def __call__(self, value):
        if value.size > self.limit:
            raise ValidationError("Receipt images must be 10 MB or smaller.")

    def __eq__(self, other):
        return isinstance(other, self.__class__)


def receipt_upload_path(instance, filename):
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    return f"receipts/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}.{extension}"

class Customer(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Quote(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('converted', 'Converted to Invoice'),
        ('expired', 'Expired / Rejected'),
    ]
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='quotes')
    service_type = models.CharField(max_length=100)
    estimated_square_footage = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, null=True)
    estimated_total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Quote #{self.id} - {self.customer.name} ({self.service_type})"


class Invoice(models.Model):
    STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ]
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='invoices')
    originating_quote = models.OneToOneField(Quote, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoice')
    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    issue_date = models.DateField(auto_now_add=True)
    paid_date = models.DateField(null=True, blank=True)
    due_date = models.DateField()
    final_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unpaid')
    created_at = models.DateTimeField(auto_now_add=True)

    # Tracking fields for pdf management
    pdf_generated = models.BooleanField(default=False, verbose_name="PDF Generated")
    pdf_emailed = models.BooleanField(default=False, verbose_name="Emailed to Client")

    def save(self, *args, **kwargs):
            if self.status == 'paid' and self.paid_date is None:
                self.paid_date = timezone.localdate()
            elif self.status != 'paid':
                self.paid_date = None

            update_fields = kwargs.get('update_fields')
            if update_fields is not None and 'status' in update_fields:
                kwargs['update_fields'] = set(update_fields) | {'paid_date'}

            # Assign sequential invoice numbers (e.g., INV-1001).
            if not self.invoice_number:
                # 1. Look up the absolute latest created invoice row in the database
                latest_invoice = Invoice.objects.order_by('-id').first()
                
                if latest_invoice and latest_invoice.invoice_number:
                    try:
                        # 2. Extract the numeric string part sitting right after 'INV-'
                        # For example: if latest was 'INV-1005', this grabs '1005'
                        number_part = latest_invoice.invoice_number.split('-')[1]
                        next_number = int(number_part) + 1
                    except (IndexError, ValueError):
                        # Fallback protection in case an old test row has a random string format
                        next_number = 1001
                else:
                    # 3. Starting baseline integer index point for your business tracking
                    next_number = 1001
                    
                self.invoice_number = f"INV-{next_number}"
                
            if not self.due_date:
                self.due_date = datetime.date.today() + datetime.timedelta(days=14)
                
            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice_number} - {self.customer.name} (${self.final_amount})"

    def send_billing_email(self):
        """Compiles an itemized spreadsheet-styled PDF and emails it directly to the customer."""
        subject = f"Invoice {self.invoice_number} from Roonscapes Lawn & Garden"
        
        message_body = (
            f"Hello {self.customer.name},\n\n"
            f"Thank you for your business! Your latest property maintenance invoice is ready for review.\n\n"
            f"Invoice Number: {self.invoice_number}\n"
            f"Total Due:      ${self.final_amount:,.2f}\n"
            f"Due Date:       {self.due_date}\n\n"
            f"We have attached a complete itemized spreadsheet breakdown copy to this email for your financial records.\n\n"
            f"Best regards,\n"
            f"Roonscapes Lawn & Garden Team"
        )
        
        line_items = []
        subtotal = Decimal('0.00')
        
        if self.originating_quote:
            quote = self.originating_quote
            sq_ft = quote.estimated_square_footage
            
            if "Basic Cut" in quote.service_type:
                if sq_ft <= 5000:
                    cut_price = Decimal('35.00')
                else:
                    intervals = math.ceil((sq_ft - 5000) / 1000)
                    cut_price = Decimal('35.00') + (Decimal(str(intervals)) * Decimal('5.00'))
                
                line_items.append({
                    'description': 'Lawn Maintenance: Basic Cut (Mow & Blow)',
                    'metric': f'{sq_ft:,} Sq Ft',
                    'total': cut_price
                })
                subtotal += cut_price

                if "Edging" in quote.service_type:
                    edge_price = Decimal('10.00')
                    if sq_ft > 5000:
                        intervals = math.ceil((sq_ft - 5000) / 1000)
                        edge_price += (Decimal(str(intervals)) * Decimal('5.00'))
                    
                    line_items.append({
                        'description': 'Lawn Maintenance Add-on: Professional Edging',
                        'metric': f'{sq_ft:,} Sq Ft',
                        'total': edge_price
                    })
                    subtotal += edge_price
                    
            elif "Weeding" in quote.service_type:
                hours = 1
                if "(" in quote.service_type and "Hours)" in quote.service_type:
                    try:
                        # Fixed the string extraction splitting crash logic safely here
                        first_split = quote.service_type.split('(')[1]
                        hours = int(first_split.split(' ')[0])
                    except (ValueError, IndexError):
                        hours = 1
                
                weeding_price = Decimal(str(hours)) * Decimal('40.00')
                line_items.append({
                    'description': 'Property Garden Maintenance: Routine Weeding',
                    'metric': f'{hours} Hours billed @ $40/hr',
                    'total': weeding_price
                })
                subtotal += weeding_price
        else:
            line_items.append({
                'description': 'Custom Groundskeeping Assignment / General Services',
                'metric': 'Flat Rate',
                'total': self.final_amount
            })
            subtotal = self.final_amount

        context_data = {
            'invoice': self,
            'line_items': line_items,
            'subtotal': subtotal,
        }
        
        html_string = render_to_string('admin/invoice_pdf.html', context_data)
        
        pdf_buffer = io.BytesIO()
        pisa.CreatePDF(io.BytesIO(html_string.encode("utf-8")), dest=pdf_buffer)
        pdf_data = pdf_buffer.getvalue()
        pdf_buffer.close()

        email = EmailMessage(
            subject=subject,
            body=message_body,
            to=[self.customer.email]
        )

        filename = f"Invoice_{self.invoice_number}.pdf"
        email.attach(filename, pdf_data, 'application/pdf')
        email.send(fail_silently=False)

        self.pdf_generated = True
        self.pdf_emailed = True
        self.save()


class Transaction(models.Model):
    TYPE_CHOICES = [
        ('income', 'Income'),
        ('expense', 'Expense'),
    ]

    transaction_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    date = models.DateField(default=timezone.localdate)
    merchant = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    receipt = models.ImageField(
        upload_to=receipt_upload_path,
        storage=PrivateReceiptStorage(),
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp']),
            ReceiptSizeValidator(),
        ],
    )
    source_invoice = models.OneToOneField(
        Invoice,
        on_delete=models.CASCADE,
        related_name='income_transaction',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-date', '-created_at')
        verbose_name = 'income / expense entry'
        verbose_name_plural = 'income / expense entries'

    def __str__(self):
        return f"{self.get_transaction_type_display()}: ${self.amount:,.2f} - {self.category}"