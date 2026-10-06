#!/bin/sh
# Install this channel on a Roku in developer mode, replacing any earlier copy.
#
#   ROKU_DEV_PASSWORD=... tools/roku_companion_app/sideload.sh ROKU_IP
#
# The password is the one you set when you enabled developer mode on the TV;
# the user name is always "rokudev". It's read from the environment so it never
# lands in a file in this repository.
set -eu
host=${1:?usage: sideload.sh ROKU_IP}
: "${ROKU_DEV_PASSWORD:?set ROKU_DEV_PASSWORD to the developer-mode password set on the TV}"
here=$(cd "$(dirname "$0")" && pwd)
zip=$(mktemp -d)/roku_companion_app.zip
(cd "$here" && zip -qr "$zip" manifest source components)
curl -sS --anyauth -u "rokudev:$ROKU_DEV_PASSWORD" -F "mysubmit=Replace" -F "archive=@$zip" \
    "http://$host/plugin_install" | grep -o "Install Success\|Identical to previous version\|Failure[^<]*" | head -1
rm -f "$zip"
