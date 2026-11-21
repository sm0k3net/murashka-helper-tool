# Install Murashka Helper Tool

## 1. Install and initialize

Run the service as an unprivileged Linux account. The workstation browser needs the public HTTPS hostname used during setup. Telegram polls outbound and requires no webhook.

    sudo apt install git python3 python3-venv
    git clone https://github.com/sm0k3net/murashka-helper-tool.git ~/murashka-helper-tool
    cd ~/murashka-helper-tool
    ./setup.sh
    ./murashka-helper init --origin https://helper.example.org

Use a fresh BotFather token, your numeric Telegram user ID and a strong independent browser approval passphrase. Prompts for secrets are hidden. State defaults to ~/.local/state/murashka-helper-tool. The CLI also accepts --state before the command. Keep state mode 0700 and config.json mode 0600.

Configure a trusted HTTPS reverse proxy to 127.0.0.1:8770. Replace helper.example.org with your real hostname in [the Caddy example](../deploy/Caddyfile.example). Serve Helper at an origin root and keep the Python listener on loopback.

## 2. Enable one or both integrations

### Murashka Remote SSH v0.2.1+

Install and configure [Remote SSH](https://github.com/sm0k3net/murashka-remote-ssh/blob/main/docs/install.md) and add hosts using its browser interface. On the Remote SSH account:

    cd ~/murashka-remote-ssh
    ./murashka hosts
    ./murashka helper-init
    ./murashka helper-broker --allow-host 1

Replace 1 with an existing host ID. Repeat --allow-host to add more hosts. Start Remote SSH itself separately so workspaces are usable. Broker and gateway share Remote SSH state. The broker has no TCP listener.

For a first installation with both products under the same account:

    cd ~/murashka-helper-tool
    ./murashka-helper configure-remote \
      --socket ~/.local/state/murashka-remote-ssh/helper.sock \
      --token-file ~/.local/state/murashka-remote-ssh/helper-token

For separate accounts, use --socket with a deliberately shared Unix socket directory. Give the gateway account write access and the Helper account directory traversal and socket group access. A setgid socket directory owned by the gateway with group traversal can supply the socket group. Store a mode 0600 copy of the broker token with the Helper account and point --token-file there. The Helper account does not need the gateway database or its encryption key.

To run the broker continuously, install the unit described in the [Remote SSH broker guide](https://github.com/sm0k3net/murashka-remote-ssh/blob/main/docs/helper-tool.md). Use the same state path and an explicit allowlist in ExecStart.

### wg-easy v15.4.0

Configure a reachable HTTPS wg-easy origin, or use a loopback HTTP listener on the same machine:

    ./murashka-helper configure-wg --url http://127.0.0.1:51821

Enter an account supported by the [upstream v15.4 API](https://wg-easy.github.io/wg-easy/v15.4/advanced/api/). Basic Auth must already be allowed for it. The upstream API does not accept a 2FA account through this flow. If your deployment requires 2FA, leave this optional adapter disabled and use the wg-easy web interface. Use a dedicated API account and the minimum upstream roles available for your use case. The integration does not change authentication settings.

The API is version-specific. Check compatibility on a test instance before changing the wg-easy release. Helper uses fixed API routes and rejects redirects and unencrypted non-loopback origins.

## 3. Verify and start

    ./murashka-helper check
    ./murashka-helper serve

Open your dedicated bot's private chat and send /help. Only the configured user ID may operate the bot. Start the browser approval service before issuing requests. For boot persistence on systemd:

    install -Dm644 deploy/murashka-helper-tool.service ~/.config/systemd/user/murashka-helper-tool.service
    systemctl --user daemon-reload
    systemctl --user enable --now murashka-helper-tool

The example assumes the checkout is ~/murashka-helper-tool. Stop an existing foreground copy before starting the unit. The administrator can enable lingering for that account if it should start at boot.

## Upgrade and recover

Keep the private state directory in a protected backup. On upgrade, stop the daemon, fetch the release, rerun ./setup.sh and restart. Pending links live in memory and expire on restart. Existing issued Remote SSH grants belong to the Remote SSH gateway and are still revocable there. If the bot token is exposed, rotate it in BotFather and replace the saved token while Helper is stopped. If the passphrase is exposed, initialize fresh private Helper state and reconfigure the integrations.
