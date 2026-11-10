# Setting up SSO with SAML

> Fictional help article for Ledgerline (Demo), a made-up invoicing app used in a demo.

## Availability

Single sign-on with SAML 2.0 is available on the Scale plan only. Only the account owner and users with the Admin role can configure it. Your identity provider must support SAML 2.0, which most business identity providers do.

## Configure Ledgerline

Go to Settings > Security > Single sign-on and select Set up SAML. Ledgerline shows two values you paste into your identity provider: the Assertion Consumer Service URL and the Entity ID. Both are specific to your account and begin with https://sso.ledgerline-demo.example.

## Configure your identity provider

In your identity provider, create a new SAML application and paste those two values. Set the name ID to the user's email address. Then copy the provider's sign-on URL and x509 certificate back into Ledgerline and select Save. Certificates must be in PEM format.

## Test before enforcing

Select Test connection to sign in with a test user. Keep SSO set to Optional at first, so people can still sign in with a password. When the test works, switch to Required. With Required on, password sign-in is blocked for all users except the account owner, who keeps a password as a fallback.

## Provisioning and troubleshooting

Users are created the first time they sign in through SSO and get the Member role by default. Ledgerline does not support automatic provisioning or deprovisioning at this time, so remove users manually when they leave. A common problem is a mismatched email address between the identity provider and Ledgerline; the sign-in page then shows a No matching user error.
