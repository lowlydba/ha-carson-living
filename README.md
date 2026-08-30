# ha-carson-living-electric-boogaloo
[![Coverage Status](https://coveralls.io/repos/github/rado0x54/ha-carson-living/badge.svg?branch=master)](https://coveralls.io/github/rado0x54/ha-carson-living?branch=master)
![Python package](https://github.com/rado0x54/ha-carson-living/workflows/Python%20package/badge.svg)

Custom integration for [Carson Living](https://www.carson.live/) for Home Assistant.

This is a fork of [pbrink231/ha-carson-living](https://github.com/pbrink231/ha-carson-living),
which is itself a fork of [rado0x54/ha-carson-living](https://github.com/rado0x54/ha-carson-living).
This fork adds support for token-based (JWT) authentication, in addition to the
original username/password login.

## Disclaimer
Please use this library at your own risk and make sure that you do not violate the
[Terms of Service of Carson](https://www.carson.live/terms).

## Installation

### HACS

Simpliest way to install is using HACS.

Use the button above or go to HACS -> 3 Dots in to right -> Custom repositories

Repository: https://github.com/lowlydba/ha-carson-living

Type: Integration

Move to setup setup below

### Manually

If you want to manually install

Copy files in this repos custom_components/carson/ folder into path/to/haconfig/custom_components/carson/

### Setup

1) Once either HACS or Manually was done (information above)
2) Devices & services
3) Add Integration
4) choose "Carson Living"
5) Login with your Carson Credentials, or see [Token authentication](#token-authentication) below
   if your account only ever signs in via Google/SSO.

## Usage

The carson app should create all the door and camera entities available on your carson account.  At this point you can use them as normal.

![image](https://github.com/user-attachments/assets/aed857ac-e09d-4d9d-bb24-8f6bf79e8b79)

## Token authentication

Carson's API has no direct login endpoint for federated logins (e.g. "Sign in with
Google"), so accounts that only ever sign in that way have no native Carson
password to enter here. For those accounts, leave "Password" blank and instead
paste a JWT into the "Token" field. This is the same token the Carson mobile app
uses on your behalf after you sign in, so you'll need to capture it once from an
already-authenticated session, e.g. via a proxy such as
[HTTP Toolkit](https://httptoolkit.com/) or mitmproxy.

Once set up, the integration renews the token automatically as needed. If you
supplied a password, renewal happens transparently; if you didn't, expect to
recapture a fresh token and update the integration once the original token
expires.
