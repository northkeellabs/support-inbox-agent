# Two-factor authentication

> Fictional help article for Ledgerline (Demo), a made-up invoicing app used in a demo.

## What it is

Two-factor authentication (2FA) adds a six-digit code from an authenticator app to your password when you sign in. Ledgerline supports TOTP apps, which generate a new code every 30 seconds. SMS codes are not offered.

## Turn on 2FA

Go to Settings > Security > Two-factor authentication > Enable. Scan the QR code with your authenticator app and enter the six-digit code to confirm. Ledgerline then shows 10 single-use backup codes. Save them in a safe place, because each code works once.

## Signing in with 2FA

Enter your email and password, then the current code from your app. If your phone clock is off by more than a minute, codes fail, so enable automatic time on your device. You can tick Trust this device for 30 days on personal computers.

## If you lose your device

First try one of your backup codes. If you have no backup code and no access to your authenticator app, you must go through identity verification handled by the security team. Support agents cannot disable 2FA, bypass it or confirm your identity themselves. Send a request through the contact form and the security team will reply with the steps.

## Requiring 2FA for your team

Admins can require 2FA for everyone under Settings > Security > Require two-factor authentication. Users without 2FA are asked to set it up at their next sign-in. This setting is available on all paid plans.
