# Recurring invoices

> Fictional help article for Ledgerline (Demo), a made-up invoicing app used in a demo.

## What recurring invoices do

A recurring invoice is a schedule that creates and optionally sends a new invoice automatically on a set cycle. They are available on Starter, Growth and Scale plans, and not on Free. Common uses are monthly retainers, subscriptions and rent.

## Set up a schedule

Follow these steps:

1. Go to Invoices > Recurring > New schedule.
2. Choose the customer and add line items as you would for a normal invoice.
3. Pick a frequency: weekly, every 2 weeks, monthly, every 3 months or yearly.
4. Choose a start date and an optional end date or number of invoices.
5. Select whether to Send automatically or Create as draft for review.

## How dates and numbering work

Each generated invoice takes the next number from your invoice numbering sequence and uses the due date rule from the schedule, for example 14 days after the issue date. Schedules run at 06:00 UTC on the scheduled day. If you pick a start day of 29, 30 or 31, see the known issues article, because short months can cause a skipped run.

## Pause, edit or stop

Open the schedule from Invoices > Recurring. Pause stops future runs without deleting the schedule; Resume restarts it at the next due date. Edits apply only to invoices created after the change. Invoices that were already generated are not altered.

## Limits

Starter accounts can have up to 10 active schedules, Growth up to 50, and Scale up to 500. Failed automatic emails, for example due to an invalid customer address, are retried once after 24 hours and then flagged on the schedule page.
