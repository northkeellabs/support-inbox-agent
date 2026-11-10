# API rate limits

> Fictional help article for Ledgerline (Demo), a made-up invoicing app used in a demo.

## The limit

The Ledgerline API allows 120 requests per minute per API key. The count uses a rolling 60-second window, so there is no fixed reset at the start of the minute. The limit is the same on Growth and Scale.

## What happens when you exceed it

Extra requests receive status 429 Too Many Requests and are not processed. The response includes a Retry-After header with the number of seconds to wait. Requests that were rejected with 429 do not count against your next window.

## Reading the headers

Every response includes X-RateLimit-Limit (always 120), X-RateLimit-Remaining and X-RateLimit-Reset, which is the number of seconds until the oldest request in the window expires. Use them to slow down before you reach zero.

## Best practices

To stay under the limit:

1. Fetch lists with limit=100 instead of many small requests.
2. Use webhooks instead of polling for changes.
3. Retry on 429 using the Retry-After value, and add random jitter.
4. Spread batch jobs out over time.

## Need a higher limit

Limits are per key, so separate integrations should use separate keys. Ledgerline does not offer a higher limit on request, and support cannot raise it for you. Custom limits are not part of any plan at this time.

## Example of handling a 429

Suppose your script sends 130 requests in 50 seconds. The first 120 succeed and the remaining 10 return 429 with Retry-After: 8. Your code should pause for 8 seconds plus a small random delay, then resend only the 10 rejected requests. Do not resend the whole batch, because that would repeat work and use up the next window.
