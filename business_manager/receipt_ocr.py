import calendar
import datetime
import re
from decimal import Decimal

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_RECEIPT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MONEY_PATTERN = re.compile(
    r"(?<!\d)(?:\$\s*)?(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+\.\d{2})(?!\d)"
)
DATE_PATTERNS = (
    re.compile(r"\b(?P<year>20\d{2})[-/.](?P<month>0?[1-9]|1[0-2])[-/.](?P<day>0?[1-9]|[12]\d|3[01])\b"),
    re.compile(r"\b(?P<month>0?[1-9]|1[0-2])[-/.](?P<day>0?[1-9]|[12]\d|3[01])[-/.](?P<year>\d{2}|20\d{2})\b"),
)
TEXT_DATE_PATTERNS = (
    re.compile(
        r"\b(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+(?P<day>[0-2]?\d|3[01]),?\s+"
        r"(?P<year>\d{2}|20\d{2})\b",
        re.IGNORECASE,
    ),
)
MONTH_LOOKUP = {
    name.lower(): month
    for month, name in enumerate(calendar.month_name)
    if name
}
MONTH_LOOKUP.update({
    name.lower(): month
    for month, name in enumerate(calendar.month_abbr)
    if name
})
TAX_PATTERN = re.compile(r"\b(?:tax|gst|hst|pst|qst|vat)\b", re.IGNORECASE)
SUBTOTAL_PATTERN = re.compile(r"\bsub[\s-]*total\b", re.IGNORECASE)
TOTAL_PATTERN = re.compile(
    r"\b(?:grand\s*total|total\s*(?:paid|due)?|amount\s*due|balance\s*due)\b",
    re.IGNORECASE,
)
NON_ITEM_PATTERN = re.compile(
    r"\b(?:tax|gst|hst|pst|vat|sub[\s-]*total|grand\s*total|total|discount|"
    r"change|cash|debit|credit|visa|mastercard|amount\s*due|balance\s*due)\b",
    re.IGNORECASE,
)


class ReceiptOCRError(Exception):
    pass


class OCRUnavailable(ReceiptOCRError):
    pass


def _parse_date(text):
    for pattern in DATE_PATTERNS + TEXT_DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        year = int(match.group("year"))
        if year < 100:
            year += 2000 if year < 70 else 1900
        month_value = match.group("month")
        month = int(month_value) if month_value.isdigit() else MONTH_LOOKUP[month_value.lower()]
        try:
            parsed = datetime.date(
                year,
                month,
                int(match.group("day")),
            )
        except ValueError:
            continue
        return parsed.isoformat()
    return ""


def _line_amount(line):
    matches = list(MONEY_PATTERN.finditer(line))
    if not matches:
        return None
    value = matches[-1].group("amount").replace(",", "")
    return Decimal(value)


def parse_receipt_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    amount_lines = []
    for line in lines:
        amount = _line_amount(line)
        if amount is not None:
            amount_lines.append((line, amount))

    subtotal = next(
        (amount for line, amount in amount_lines if SUBTOTAL_PATTERN.search(line)),
        None,
    )
    tax_values = [
        amount
        for line, amount in amount_lines
        if TAX_PATTERN.search(line) and not SUBTOTAL_PATTERN.search(line)
    ]
    tax_amount = sum(tax_values, Decimal("0.00"))

    total = next(
        (amount for line, amount in reversed(amount_lines) if TOTAL_PATTERN.search(line)),
        None,
    )
    if total is None and amount_lines:
        total = max(amount for _, amount in amount_lines)
    if total is None:
        total = Decimal("0.00")
    if subtotal is not None and not tax_values and total >= subtotal:
        tax_amount = total - subtotal

    merchant = ""
    for line in lines[:8]:
        if (
            len(line) <= 120
            and not re.search(r"\d{3,}", line)
            and not re.search(r"\b(?:receipt|invoice|date|cashier|terminal|www)\b", line, re.I)
        ):
            merchant = line
            break

    items = []
    for line, _ in amount_lines:
        if NON_ITEM_PATTERN.search(line):
            continue
        item = MONEY_PATTERN.sub("", line).strip(" \t-:$")
        if item and item not in items:
            items.append(item)

    return {
        "date": _parse_date("\n".join(lines)),
        "merchant": merchant[:120],
        "description": ", ".join(items)[:200],
        "subtotal": "" if subtotal is None else f"{subtotal:.2f}",
        "tax_amount": f"{tax_amount:.2f}",
        "amount": f"{total:.2f}",
        "category": "Receipt purchase",
        "transaction_type": "expense",
    }


def extract_receipt_image(uploaded_file):
    if uploaded_file.size > MAX_RECEIPT_BYTES:
        raise ReceiptOCRError("Receipt images must be 10 MB or smaller.")

    try:
        image = Image.open(uploaded_file)
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ReceiptOCRError("Choose a valid JPG, PNG, or WebP receipt image.")
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ReceiptOCRError("Receipt image dimensions are too large to process.")
        image.verify()
        uploaded_file.seek(0)
        image = ImageOps.exif_transpose(Image.open(uploaded_file)).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ReceiptOCRError("Choose a valid JPG, PNG, or WebP receipt image.") from exc

    try:
        import pytesseract
    except ImportError as exc:
        raise OCRUnavailable(
            "The local OCR Python package is missing. Install the project requirements."
        ) from exc

    tesseract_cmd = getattr(settings, "TESSERACT_CMD", "")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    try:
        recognized_text = pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRUnavailable(
            "Tesseract OCR is not installed or configured on this PC. Install it or set TESSERACT_CMD."
        ) from exc
    except pytesseract.TesseractError as exc:
        raise ReceiptOCRError(
            "The local OCR engine could not read this image. Check Tesseract and its English language data."
        ) from exc

    if not recognized_text.strip():
        raise ReceiptOCRError(
            "No text was found. Try a sharper, well-lit photo with the full receipt in frame."
        )
    return parse_receipt_text(recognized_text)
