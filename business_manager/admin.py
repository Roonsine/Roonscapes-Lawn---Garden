import datetime
from django.contrib import admin
from django.contrib import messages
from django.db.models import Sum
from unfold.admin import ModelAdmin

# Import your database tables directly from models.py
from .models import Customer, Quote, Invoice

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
    list_display = ('invoice_number', 'customer', 'final_amount', 'status', 'due_date', 'issue_date')
    list_filter = ('status', 'due_date', 'issue_date')
    search_fields = ('invoice_number', 'customer__name', 'customer__email')
    readonly_fields = ('invoice_number', 'issue_date', 'created_at')
    ordering = ('-issue_date',)
    
    # Dropdown menu action shortcut to trigger emails
    actions = ['email_selected_invoices']

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
        ('Financial Terms', {'fields': ('final_amount', 'status', 'due_date')}),
        ('System Timestamps', {'fields': ('issue_date', 'created_at'), 'classes': ('collapse',)}),
    ]


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


# ========================================================
# 3. NATIVE UNFOLD DASHBOARD CALLBACK HOOK
# ========================================================
def dashboard_callback(request, context):
    """
    Native hook executed globally by Unfold to pass your database
    numbers directly into the templates/admin/index.html view layer.
    """
    context['pending_quotes_count'] = Quote.objects.filter(status='pending').count()
    context['unpaid_invoices_count'] = Invoice.objects.filter(status='unpaid').count()
    
    raw_revenue = Invoice.objects.filter(status='unpaid').aggregate(Sum('final_amount'))['final_amount__sum'] or 0
    context['unpaid_financials'] = f"${raw_revenue:,.2f}"
    
    return context
