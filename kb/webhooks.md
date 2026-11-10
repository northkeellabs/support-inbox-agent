# Webhooks

> Fictional help article for Ledgerline (Demo), a made-up invoicing app used in a demo.

## What webhooks are

Webhooks send an HTTPS POST request to your server when something happens in Ledgerline, such as invoice.paid, invoice.sent or customer.created. They are available on Growth and Scale plans. Each event has a unique id and a JSON body.

## Add an endpoint

Go to Settings > Developers > Webhooks > Add endpoint. Enter your HTTPS URL and select the event types you want. After saving, Ledgerline shows a signing secret once. Store it safely. You can have up to 5 endpoints per account and can send a test event from the endpoint page.

## Verify the signature

Each request carries an X-Ledgerline-Signature header. It is an HMAC-SHA256 of the raw request body, calculated with your signing secret and hex encoded. Compute the same value on your server and compare it using a constant-time comparison. Reject any request whose signature does not match.

## Retries and responses

Your endpoint should answer with a 2xx status within 10 seconds. If it does not, Ledgerline retries the delivery 6 times over 24 hours with exponential backoff. After the sixth failed attempt the event is marked failed, and an endpoint that fails continuously for 7 days is disabled and the account owner is emailed.

## Duplicates and ordering

Delivery is at least once, so the same event can arrive more than once, and events can arrive out of order. Store the event id and ignore ids you have already processed. See the known issues article for a duplicate delivery problem and its workaround.
