# API overview and authentication

> Fictional help article for Ledgerline (Demo), a made-up invoicing app used in a demo.

## Who can use the API

The Ledgerline API is available on Growth and Scale plans only. On other plans the API keys page is hidden. The API is a JSON REST API served from api.ledgerline-demo.example/v1 and lets you read and create invoices, customers and payments.

## Create an API key

Go to Settings > Developers > API keys > Create key. Give the key a name, choose Read only or Read and write, and select Create. The full key is shown only once, so copy it into a secrets manager immediately. Each account can hold up to 10 active keys.

## Authenticate requests

Send the key as a bearer token in the Authorization header, in the form Authorization: Bearer YOUR_KEY. Requests must use HTTPS. Requests without a valid key return status 401, and keys without write permission that try to change data return status 403.

## Rotate or revoke a key

To rotate, create a new key, update your application, then revoke the old one under Settings > Developers > API keys. Revoking takes effect within a minute. If you think a key has leaked, revoke it first and then contact support to report the issue, because the security team may need to review recent activity.

## Pagination and errors

List endpoints return up to 100 items per page and use a cursor parameter. Errors are returned as JSON with a code and message. Status 429 means you hit the rate limit, described in the API rate limits article. Idempotency is supported on POST requests through the Idempotency-Key header, kept for 24 hours.
