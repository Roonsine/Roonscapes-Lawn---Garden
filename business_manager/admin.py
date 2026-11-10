import mimetypes
import datetime
from django.contrib import admin
from django.contrib import messages
from django.http import FileResponse, HttpResponseNotAllowed, HttpResponseNotFound, JsonResponse
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.urls import path
from unfold.admin import ModelAdmin
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone

# Import your database tables directly from models.py
from .models import Customer, Quote, Invoice, Transaction
from .receipt_ocr import OCRUnavailable, ReceiptOCRError, extract_receipt_image

# ========================================================
# 1. MODEL DASHBOARDS & AUTOMATION UTILITIES
# ========================================================

class CustomerAdmin(ModelAdmin):
    list_display = ('name', 'email', 'phone', 'created_at')
    search_fields = ('name', 'email', 'phone', 'address')
    list_per_page = 25


class QuoteAdmin(ModelAdmin):
    list_display = ('id', 'customer', 'service_type', 'estimated_square_footage', 'estimated_total', 'status', 'created_at')
    list_filter = ('status', 'service_type', 'created_at')
    search_fields = ('customer__name', 'customer__email', 'service_type')
    ordering = ('-created_at',)
    
    # Dropdown menu action shortcut to convert quotes
    actions = ['convert_quotes_to_invoices']

    @admin.action(description="Convert selected pending quotes to unpaid invoices")
    def convert_quotes_to_invoices(self, request, queryset):
        """Batch processes selected pending customer estimates into official unpaid bills."""
        pending_quotes = queryset.filter(status='pending')
        converted_count = 0

        for quote in pending_quotes:
            Invoice.objects.create(
                customer=quote.customer,
                originating_quote=quote,
                due_date=datetime.date.today() + datetime.timedelta(days=14),
                final_amount=quote.estimated_total,
                status='unpaid'
            )
            quote.status = 'converted'
            quote.save()
            converted_count += 1

        if converted_count > 0:
            self.message_user(request, f"Successfully processed {converted_count} quote(s) into actionable invoices.", messages.SUCCESS)
        else:
            self.message_user(request, "No invoices were created. Make sure the quotes you selected are marked as 'Pending Review'.", messages.WARNING)


class InvoiceAdmin(ModelAdmin):
    list_display = ('invoice_number', 'customer', 'final_amount', 'status', 'paid_date', 'pdf_generated', 'pdf_emailed', 'download_pdf_button', 'due_date')
    list_filter = ('status', 'pdf_generated', 'pdf_emailed', 'due_date')
    search_fields = ('invoice_number', 'customer__name', 'customer__email')
    readonly_fields = ('invoice_number', 'issue_date', 'created_at')
    ordering = ('-issue_date',)
    
    actions = ['email_selected_invoices']


    def download_pdf_button(self, obj):
            """Generates a styled, clickable down-arrow button right inside the table row grid."""
            download_url = reverse('download_invoice_pdf', args=[obj.id])
            return format_html(
                '<a href="{}" class="bg-slate-800 text-white hover:bg-slate-700 font-bold py-1 px-3 rounded text-xs transition-colors inline-block">⬇️ Download PDF</a>',
                download_url
            )
    download_pdf_button.short_description = "Actions" # Table column header text title


    @admin.action(description="Email selected invoices to customers")
    def email_selected_invoices(self, request, queryset):
        """Batch triggers individual outbound email notifications with PDF spreadsheet attachments."""
        sent_count = 0
        for invoice in queryset:
            invoice.send_billing_email()
            sent_count += 1
            
        self.message_user(request, f"Successfully emailed {sent_count} invoice notification alert(s).", messages.SUCCESS)

    fieldsets = [
        ('Core Parameters', {'fields': ('invoice_number', 'customer', 'originating_quote')}),
        ('Financial Terms', {'fields': ('final_amount', 'status', 'paid_date', 'due_date')}),
        ('System Timestamps', {'fields': ('issue_date', 'created_at'), 'classes': ('collapse',)}),
    ]


class TransactionAdmin(ModelAdmin):
    change_form_template = 'admin/business_manager/transaction/change_form.html'
    list_display = ('date', 'transaction_type', 'merchant', 'category', 'description', 'amount', 'tax_amount', 'receipt_link')
    list_filter = ('transaction_type', 'category', 'date')
    search_fields = ('merchant', 'category', 'description')
    ordering = ('-date', '-created_at')
    date_hierarchy = 'date'
    readonly_fields = ('source_invoice', 'created_at', 'receipt_preview')
    fieldsets = [
        ('Transaction details', {
            'fields': ('transaction_type', 'date', 'merchant', 'category', 'description'),
        }),
        ('Amounts', {'fields': ('subtotal', 'tax_amount', 'amount')}),
        ('Receipt', {
            'fields': ('receipt', 'receipt_preview'),
            'description': 'Upload a clear receipt photo, then use Read receipt to fill suggested values. Review them before saving.',
        }),
        ('Invoice link', {'fields': ('source_invoice', 'created_at')}),
    ]

    class Media:
        js = ('business_manager/receipt_ocr.js',)

    def get_urls(self):
        custom_urls = [
            path(
                'receipt-ocr/',
                self.admin_site.admin_view(self.receipt_ocr_view),
                name='business_manager_transaction_receipt_ocr',
            ),
            path(
                'receipt-file/<path:receipt_name>/',
                self.admin_site.admin_view(self.receipt_file_view),
                name='business_manager_transaction_receipt_file',
            ),
        ]
        return custom_urls + super().get_urls()

    def receipt_file_view(self, request, receipt_name):
        transaction = get_object_or_404(
            self.get_queryset(request),
            receipt=receipt_name,
        )
        if not transaction.receipt:
            return HttpResponseNotFound('No receipt image is attached to this entry.')
        content_type = mimetypes.guess_type(transaction.receipt.name)[0] or 'application/octet-stream'
        return FileResponse(transaction.receipt.open('rb'), content_type=content_type)

    def receipt_ocr_view(self, request):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        receipt = request.FILES.get('receipt')
        if receipt is None:
            return JsonResponse({'error': 'Choose a receipt image first.'}, status=400)

        try:
            suggested_fields = extract_receipt_image(receipt)
        except OCRUnavailable as exc:
            return JsonResponse({'error': str(exc)}, status=503)
        except ReceiptOCRError as exc:
            return JsonResponse({'error': str(exc)}, status=422)

        return JsonResponse({'fields': suggested_fields})

    @admin.display(description='Receipt')
    def receipt_link(self, obj):
        if not obj or not obj.receipt:
            return '—'
        url = obj.receipt.url
        return format_html('<a href="{}">View receipt</a>', url)

    @admin.display(description='Uploaded receipt')
    def receipt_preview(self, obj):
        return self.receipt_link(obj)


# ========================================================
# 2. SYSTEM REGISTRATIONS
# ========================================================
# Safely clear out any lingering registration memory to prevent duplicate table crash errors
try:
    admin.site.unregister(Customer)
    admin.site.unregister(Quote)
    admin.site.unregister(Invoice)
except admin.sites.NotRegistered:
    pass

admin.site.register(Customer, CustomerAdmin)
admin.site.register(Quote, QuoteAdmin)
admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Transaction, TransactionAdmin)


def dashboard_callback(request, context):
    """
    Native hook executed globally by Unfold to pass your database
    numbers directly into the templates/admin/index.html view layer.
    """
    # 1. Fetch real-time row calculations from the database
    pending_quotes_count = Quote.objects.filter(status='pending').count()
    unpaid_invoices_count = Invoice.objects.filter(status='unpaid').count()
    
    # 2. Sum your unpaid financials safely with a fallback default of 0
    raw_revenue = Invoice.objects.filter(status='unpaid').aggregate(Sum('final_amount'))['final_amount__sum'] or 0
    unpaid_financials = f"${raw_revenue:,.2f}"

    today = timezone.localdate()
    month_start = today.replace(day=1)
    month_transactions = Transaction.objects.filter(date__gte=month_start, date__lte=today)
    monthly_income = month_transactions.filter(transaction_type='income').aggregate(
        total=Sum('amount')
    )['total'] or 0
    monthly_expenses = month_transactions.filter(transaction_type='expense').aggregate(
        total=Sum('amount')
    )['total'] or 0
    monthly_net = monthly_income - monthly_expenses

    # 3. CRITICAL INTERNALS CONNECT: Map these directly into a dictionary loop list for your index template
    context.update({
        "kpi_metrics": [
            {
                "title": "Pending Quote Requests",
                "metric": pending_quotes_count,
                "description": "Incoming client estimates requiring manual review.",
            },
            {
                "title": "Outstanding Invoices",
                "metric": unpaid_invoices_count,
                "description": "Active bills currently waiting on client payment clearance.",
            },
            {
                "title": "Unpaid Revenue Pipeline",
                "metric": unpaid_financials,
                "description": "Total gross capital currently sitting out in the field.",
            },
        ]
        + [
            {
                "title": "Income This Month",
                "metric": f"${monthly_income:,.2f}",
                "description": "Payments and other income recorded this month.",
            },
            {
                "title": "Expenses This Month",
                "metric": f"${monthly_expenses:,.2f}",
                "description": "Business expenses recorded this month.",
            },
            {
                "title": "Net This Month",
                "metric": f"${monthly_net:,.2f}",
                "description": "Recorded income minus recorded expenses this month.",
            },
        ],
        "recent_transactions": Transaction.objects.all()[:5],
        "transaction_add_url": reverse('admin:business_manager_transaction_add'),
        "transaction_list_url": reverse('admin:business_manager_transaction_changelist'),
    })
    
    return context