# Murashka Helper Tool

A self-hosted Telegram companion for [Murashka Remote SSH](https://github.com/sm0k3net/murashka-remote-ssh) and wg-easy. Check host status from your phone. Approve sensitive operations in a separate HTTPS browser page.

| Integration | From Telegram | After browser approval |
| --- | --- | --- |
| Remote SSH | List allowed hosts and see the last resource sample | Open a 30-minute guest workspace for one host or revoke a workspace issued by Helper |
| wg-easy | List VPN profile IDs, names and enabled state | Create, enable or disable profiles and download WireGuard configurations |

**Example:** send /hosts then /connect 1. Open the five-minute approval link, enter the independent operator passphrase, and open Remote SSH with the displayed temporary password.

- [Project website](https://sm0k3net.github.io/murashka-remote-ssh/helper-tool/)
- [Install and configure](docs/install.md)
- [Command examples and runbook](docs/usage.md)
- [Security model and reporting](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [GitHub releases](https://github.com/sm0k3net/murashka-helper-tool/releases)

## Quick start

Use Python 3.12+ on Linux. Create a dedicated Telegram bot through [BotFather](https://t.me/BotFather), reserve an HTTPS hostname for browser approvals, and follow the guided prompts:

    git clone https://github.com/sm0k3net/murashka-helper-tool.git
    cd murashka-helper-tool
    ./setup.sh
    ./murashka-helper init --origin https://helper.example.org

Configure either integration and the HTTPS reverse proxy before running the bot. Remote SSH requires v0.2.1 or newer. The VPN adapter targets wg-easy v15.4.0 and its documented Basic Auth API.

Helper is configured for one operator and one private bot chat. Proxy services, Vaultwarden and backup providers are outside v0.1. See the install guide for the credentials and permissions each integration requires.

Apache-2.0. [License](LICENSE)
