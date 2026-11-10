# Payment failures and retries

> Fictional help article for Ledgerline (Demo), a made-up invoicing app used in a demo.

## Why an online payment fails

The most common reasons are insufficient funds, an expired card, a card issuer declining an online charge, or a failed 3-D Secure check. The reason code is shown on the invoice under Payments > Attempts, so you can tell the customer what happened. Ledgerline does not see full card numbers.

## What the customer sees

The customer sees an error on the payment page and can try again right away with the same card or another method. The invoice stays Unpaid, and automatic reminders continue as scheduled. A failed attempt never marks an invoice as paid.

## Automatic retries for subscriptions

This applies to your Ledgerline subscription charge, not your customer invoices. If a subscription payment fails, Ledgerline retries it 3 times, on day 3, day 5 and day 7 after the first failure, and emails the account owner each time. If all retries fail, the account moves to the Free plan limits but your data is kept.

## Update a card

To fix a failed subscription payment, go to Settings > Billing > Payment method and select Replace card. A new card is charged straight away if there is an outstanding balance. Only the account owner and users with the Billing role can change the card.

## Still stuck

If a payment was taken but the invoice shows Unpaid after 15 minutes, send the invoice number and the date of the payment to support. Do not send full card numbers by email. Support can check records but cannot refund or reverse a payment; refunds are covered in the refunds policy article.
