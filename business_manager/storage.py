from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.urls import reverse
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateReceiptStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.BASE_DIR / 'private_receipts')

    def url(self, name):
        return reverse(
            'admin:business_manager_transaction_receipt_file',
            args=[name],
        )
