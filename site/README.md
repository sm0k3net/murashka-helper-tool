# Project site

The published site is available in the [Murashka Pages deployment](https://sm0k3net.github.io/murashka-remote-ssh/helper-tool/). This repository keeps its own copy of the static source: the root index.html and the assets in site/. To stage a site update, preview these files, then synchronize the static copy in the Remote SSH repository.

For a dedicated URL under this repository, select **Settings → Pages → Deploy from a branch → main → / (root)**. The existing Jekyll configuration excludes the application, deployment files and documentation from the Pages output.

To preview locally:

    python3 -m http.server 8080 --bind 127.0.0.1
