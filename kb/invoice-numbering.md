# Invoice numbering

> Fictional help article for Ledgerline (Demo), a made-up invoicing app used in a demo.

## Default numbering

New accounts use the format INV-0001, increasing by one for each invoice. Numbers are assigned when an invoice is created, not when it is sent, so a saved draft already holds its number.

## Change the prefix or next number

Go to Settings > Invoices > Numbering. You can change the prefix (up to 10 characters), the number of digits (3 to 8) and the next number. For example, a prefix of 2026- with 4 digits gives 2026-0001. The next number can only be raised, never lowered below the highest number already used, to prevent duplicates.

## Gaps and voided invoices

Deleting a draft frees its number only if it was the most recent one. Voiding a sent invoice keeps the number reserved and marks the invoice as Void, which keeps an auditable sequence. Many tax authorities expect gap-free numbering, so voiding is usually the right choice.

## Separate sequences

Growth and Scale accounts can add extra sequences, for example one per brand or per currency, from Settings > Invoices > Numbering > Add sequence. Starter and Free accounts have one sequence. Credit notes always use their own sequence with the prefix CN-.

## Recurring invoices

Invoices created by a recurring schedule use the same sequence as manual invoices unless you choose a different one in the schedule settings. If two schedules run at the same moment, numbers are still assigned one at a time with no duplicates.
