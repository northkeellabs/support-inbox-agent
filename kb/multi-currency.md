# Multi-currency invoicing

> Fictional help article for Ledgerline (Demo), a made-up invoicing app used in a demo.

## Which plans include it

Multi-currency is available on Starter, Growth and Scale. Free accounts invoice in their single default currency only. Over 40 currencies are supported, including USD, EUR, GBP, CAD, AUD and JPY.

## Invoice in a customer's currency

Set a default currency on the customer record under Customers > Edit > Currency, or choose the currency on the invoice itself using the drop-down beside the invoice number. All line items, taxes and totals are then shown in that currency. You cannot mix currencies inside one invoice.

## Exchange rates

Ledgerline shows an indicative exchange rate on reports, refreshed once per day at 00:00 UTC. The rate is used only to convert totals into your home currency for dashboards. It does not change what the customer owes. The invoice amount is always fixed in the invoice currency.

## Payments in other currencies

When you accept online payments, the payment is collected in the invoice currency where your payment connection supports it. If the connection does not support the currency, the pay button is hidden and the invoice page shows your manual payment instructions instead. Any conversion fees charged by your bank or payment provider are not controlled by Ledgerline.

## Reports and rounding

Go to Reports > Revenue and select Home currency to see totals converted at the daily rate. Amounts are rounded to the currency's standard decimal places, for example 0 for JPY and 2 for USD. Rounding differences of up to one minor unit can appear on invoices with many lines and percentage taxes.
