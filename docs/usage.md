# Command examples

## Open staging from a phone

1. Send /hosts and locate staging's ID, for example 1.
2. Send /status 1 to see the last collected CPU, RAM and disk snapshot. Helper does not trigger an SSH sampling job.
3. Send /connect 1. Open the five-minute link and confirm the displayed action with your independent passphrase.
4. The browser shows the Remote SSH link, temporary password and grant ID. Open the SSH workspace and enter that password.
5. To stop the access early, send /revoke GRANT_ID and approve it in the browser.

## Set up and later disable a VPN device

1. Send /vpn-new Travel laptop and approve it in the browser.
2. The browser shows the new profile ID. Send /vpn-config ID, approve the download and import the resulting .conf file into the WireGuard client.
3. Send /vpn to see profile status. To revoke access without deleting the profile, send /vpn-disable ID and approve it. Use /vpn-enable ID to restore access.

Treat downloads like passwords. Profile names and enabled state appear in the private Telegram conversation. A pending request expires after five minutes and can be approved once. If the operation fails after approval, check the upstream service before retrying a state change.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Telegram ignores messages | Private chat, the exact configured numeric user ID, only one poller and no active webhook |
| Approval link does not work | Correct HTTPS origin, fresh link and an active local daemon |
| Remote SSH unavailable | Broker socket permissions, token file, host allowlist and Remote SSH state |
| wg-easy rejects Basic Auth | v15.4.0 API, TLS and permission to use Basic Auth on that account |
| VPN or SSH credentials missing from chat | Open the approval link in the browser to obtain them |
