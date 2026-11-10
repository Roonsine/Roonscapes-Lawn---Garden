(function () {
    const button = document.getElementById('read-receipt-button');
    const status = document.getElementById('receipt-ocr-status');
    const receiptInput = document.getElementById('id_receipt');

    if (!button || !status || !receiptInput) {
        return;
    }

    function getCookie(name) {
        const cookie = document.cookie
            .split('; ')
            .find((value) => value.startsWith(`${name}=`));
        return cookie ? decodeURIComponent(cookie.split('=').slice(1).join('=')) : '';
    }

    button.addEventListener('click', async function () {
        const file = receiptInput.files[0];
        if (!file) {
            status.textContent = 'Choose a receipt photo before selecting Read receipt.';
            return;
        }

        const formData = new FormData();
        formData.append('receipt', file);
        button.disabled = true;
        status.textContent = 'Reading receipt on this PC…';

        try {
            const response = await fetch(button.dataset.ocrUrl, {
                method: 'POST',
                body: formData,
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken'),
                },
            });
            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || 'Receipt could not be read.');
            }

            const fields = result.fields;
            const fieldIds = {
                transaction_type: 'id_transaction_type',
                date: 'id_date',
                merchant: 'id_merchant',
                category: 'id_category',
                description: 'id_description',
                subtotal: 'id_subtotal',
                tax_amount: 'id_tax_amount',
                amount: 'id_amount',
            };

            Object.entries(fieldIds).forEach(([key, id]) => {
                const field = document.getElementById(id);
                if (field && fields[key] !== undefined && fields[key] !== '') {
                    field.value = fields[key];
                }
            });

            status.textContent = 'Receipt read. Review and correct every suggested value before saving.';
        } catch (error) {
            status.textContent = error.message || 'Receipt could not be read.';
        } finally {
            button.disabled = false;
        }
    });
})();
