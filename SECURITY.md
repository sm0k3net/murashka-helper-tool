# Security policy

The latest release receives fixes. Report problems privately through GitHub security advisories when available or contact the repository maintainer directly. Include versions and a synthetic reproduction. Keep tokens, configs, grant URLs and logs containing credentials out of public issues.

## Boundaries

- One numeric Telegram operator is allowed in a private chat. Telegram sees profile and host display names, sampled status, and request links. Browser approval also requires an independent passphrase.
- The web service binds to loopback. Put it behind trusted HTTPS. Requests expire after five minutes, require the configured Origin, and can be approved once. The passphrase verifier uses scrypt. Keep the HTTPS host and gateway account controlled by the operator.
- The local Remote SSH broker accepts a private token and explicitly allowed host IDs. It issues only fixed-duration guest workspaces and can revoke its own grants. Guest workspaces inherit the permissions of the configured SSH account on that host.
- WireGuard configurations contain private keys. Helper returns them only as HTTPS attachments after approval. Store them securely and disable the affected VPN profile if a config is exposed.
- The wg-easy adapter uses direct Basic Auth over HTTPS or IPv4/IPv6 loopback. Upstream credentials grant all rights assigned to that account. Keep the API private and use the narrowest available account. The Helper state directory is restricted to the service account and stores upstream credentials and the bot token in a private file. Protect backups of this directory.
- A shared Unix user can read both products' files. Use distinct service accounts and a deliberately shared socket directory if process separation is required.
