# Retrieval-threshold calibration, 2026-11-10

Embedding model: bge-m3. Index: 27 articles, 137 chunks, fingerprint c36c57841018cc4d.
Score = cosine similarity of the best vector match for the ticket (subject + body). The eval tickets were not used.

- Answerable (10): min 0.628, mean 0.741
- Not answerable (5): max 0.677, mean 0.571
- Threshold: 0.66 (groups overlap: cut with best balanced accuracy (85%))

| case | answerable | top vector score | expected source in top 5 | top 3 chunks |
|---|---|---|---|---|
| cal-01-custom-numbering | True | 0.764 | True | invoice-numbering#1, invoice-numbering#2, creating-your-first-invoice#1 |
| cal-02-add-user | True | 0.673 | True | subscription-billing-and-receipts#4, user-roles-and-permissions#2, user-roles-and-permissions#4 |
| cal-03-logo-upload | True | 0.839 | True | invoice-templates-and-branding#2, known-issues#5, getting-started#2 |
| cal-04-auto-reminders | True | 0.759 | True | sending-invoices-and-reminders#3, subscription-billing-and-receipts#5, sending-invoices-and-reminders#4 |
| cal-05-record-bank-transfer | True | 0.726 | True | recording-manual-payments#1, accepting-online-payments#4, recording-manual-payments#2 |
| cal-06-enable-2fa | True | 0.793 | True | two-factor-authentication#5, two-factor-authentication#1, two-factor-authentication#4 |
| cal-07-contact-hours | True | 0.800 | True | contacting-support#1, getting-started#5, payment-failures-and-retries#5 |
| cal-08-privacy-request | True | 0.667 | True | gdpr-data-requests#1, gdpr-data-requests#5, data-export#5 |
| cal-09-downgrade | True | 0.628 | True | changing-or-cancelling-your-plan#2, recording-manual-payments#5, api-rate-limits#1 |
| cal-10-failed-payment | True | 0.765 | True | payment-failures-and-retries#4, payment-failures-and-retries#1, payment-failures-and-retries#3 |
| cal-11-offtopic-code | False | 0.515 | - | data-export#4, api-overview-and-authentication#5, payment-failures-and-retries#1 |
| cal-12-offtopic-recipe | False | 0.420 | - | invoice-templates-and-branding#4, known-issues#2, contacting-support#3 |
| cal-13-payroll | False | 0.677 | - | taxes-and-vat#5, getting-started#1, pricing-and-plans#1 |
| cal-14-inventory | False | 0.652 | - | sending-invoices-and-reminders#1, gdpr-data-requests#4, getting-started#4 |
| cal-15-linux-app | False | 0.589 | - | feature-requests-and-roadmap#4, getting-started#4, recurring-invoices#1 |
