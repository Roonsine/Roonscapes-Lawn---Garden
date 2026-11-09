import io
import math
from decimal import Decimal
from django.http import FileResponse, Http404
from django.contrib.admin.views.decorators import staff_member_required
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from .models import Invoice

@staff_member_required
def download_invoice_pdf(request, invoice_id):
    """Generates the spreadsheet invoice template on the fly and streams it as a file download."""
    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        raise Http404("Invoice not found")

    # Reconstruct line items dynamically for the spreadsheet template context mapping
    line_items = []
    subtotal = Decimal('0.00')
    
    if invoice.originating_quote:
        quote = invoice.originating_quote
        sq_ft = quote.estimated_square_footage
        
        if "Basic Cut" in quote.service_type:
            if sq_ft <= 5000:
                cut_price = Decimal('35.00')
            else:
                intervals = math.ceil((sq_ft - 5000) / 1000)
                cut_price = Decimal('35.00') + (Decimal(str(intervals)) * Decimal('5.00'))
            
            line_items.append({'description': 'Lawn Maintenance: Basic Cut (Mow & Blow)', 'metric': f'{sq_ft:,} Sq Ft', 'total': cut_price})
            subtotal += cut_price

            if "Edging" in quote.service_type:
                edge_price = Decimal('10.00')
                if sq_ft > 5000:
                    intervals = math.ceil((sq_ft - 5000) / 1000)
                    edge_price += (Decimal(str(intervals)) * Decimal('5.00'))
                line_items.append({'description': 'Lawn Maintenance Add-on: Professional Edging', 'metric': f'{sq_ft:,} Sq Ft', 'total': edge_price})
                subtotal += edge_price
    else:
        line_items.append({'description': 'Custom Groundskeeping Assignment / General Services', 'metric': 'Flat Rate', 'total': invoice.final_amount})
        subtotal = invoice.final_amount

    context_data = {'invoice': invoice, 'line_items': line_items, 'subtotal': subtotal}
    html_string = render_to_string('admin/invoice_pdf.html', context_data)
    
    # Render PDF straight into system RAM buffer
    pdf_buffer = io.BytesIO()
    pisa.CreatePDF(io.BytesIO(html_string.encode("utf-8")), dest=pdf_buffer)
    pdf_buffer.seek(0)
    
    # Toggle generated marker to True upon download access request execution
    if not invoice.pdf_generated:
        invoice.pdf_generated = True
        invoice.save()

    return FileResponse(pdf_buffer, as_attachment=True, filename=f"Invoice_{invoice.invoice_number}.pdf")
