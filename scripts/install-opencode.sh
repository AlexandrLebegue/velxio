#!/bin/sh
# Pinned optional runtime for Dockerfile.standalone. No user configuration.
set -eu
opencode_arch="${1:-$(uname -m)}"
case "$opencode_arch" in
  amd64|x86_64)
    opencode_asset=opencode-linux-x64-baseline.tar.gz
    opencode_sha=531cff2441129c30f0edd5878af494108ad07f5feb46d7ee29a2a5b830a5765d ;;
  arm64|aarch64)
    opencode_asset=opencode-linux-arm64.tar.gz
    opencode_sha=7900818a6a98881edbbadab4b7525940eff3b9750040c200481f9f56cacee405 ;;
  *) echo "Unsupported OpenCode architecture: $opencode_arch" >&2; exit 1 ;;
esac
opencode_tmp="$(mktemp -d)"
trap 'rm -rf "$opencode_tmp"' EXIT HUP INT TERM
curl --fail --location --retry 3 \
  "https://github.com/anomalyco/opencode/releases/download/v1.19.3/$opencode_asset" \
  --output "$opencode_tmp/opencode.tar.gz"
echo "$opencode_sha  $opencode_tmp/opencode.tar.gz" | sha256sum -c -
tar -xzf "$opencode_tmp/opencode.tar.gz" -C "$opencode_tmp"
install -m 0755 "$opencode_tmp/opencode" /usr/local/bin/opencode
mkdir -p /usr/local/share/licenses/opencode
curl --fail --location --retry 3 \
  https://raw.githubusercontent.com/anomalyco/opencode/v1.19.3/LICENSE \
  --output /usr/local/share/licenses/opencode/LICENSE
/usr/local/bin/opencode --version
