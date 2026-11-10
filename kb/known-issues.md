# Known issues and workarounds

> Fictional help article for Ledgerline (Demo), a made-up invoicing app used in a demo.

## PDF preview is blank in one older browser version

Symptoms: the invoice preview pane or the PDF viewer shows a blank white page on older versions of one browser. The invoice itself is fine. Workaround: select Download PDF instead of previewing it, or update the browser to its latest version. Status: the engineering team is working on a fix for the preview component.

## Recurring invoice skipped when the start date is the 31st

Symptoms: a monthly recurring schedule that starts on the 31st (or the 29th or 30th) does not create an invoice in shorter months. Workaround: edit the schedule and set the start day to 28, which exists in every month. The skipped invoice can be created by duplicating the previous invoice. Status: a fix is under way.

## Webhook events delivered more than once

Symptoms: your endpoint receives the same event twice, with the same event id, sometimes a few seconds apart. Cause: delivery is at least once and a retry can overlap with a slow first response. Workaround: store the event id of every processed event and ignore any id you have seen before, and answer with 2xx quickly.

## CSV export dates appear in US format

Symptoms: dates in an exported CSV look like 03/14/2026 when you expect 14/03/2026. Workaround: go to Settings > Business > Regional settings and change Date format, then request a new export. Files already exported are not changed.

## Logo missing on invoices after upload

Symptoms: you upload a logo and it does not show on the PDF. Cause: SVG files are not supported. Workaround: upload a PNG or JPG up to 2 MB under Settings > Business and regenerate the PDF.
