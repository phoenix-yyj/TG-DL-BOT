#!/bin/sh
set -eu

# Unraid's default share account is nobody:users (99:100).  Keep these
# configurable for other NAS distributions, but use the Unraid defaults.
PUID="${PUID:-99}"
PGID="${PGID:-100}"

case "$PUID:$PGID" in
    *[!0-9:]*|:*)
        echo "PUID and PGID must be numeric" >&2
        exit 1
        ;;
esac

mkdir -p /app/downloads /app/sessions /app/attached_assets

# Bind mounts are commonly created as root on Unraid.  Fix only the shared
# application directories here; sessions and configuration may contain
# credentials and must not be made world-readable.
chown -R "$PUID:$PGID" /app/downloads
find /app/downloads -type d -exec chmod 0777 {} +
find /app/downloads -type f -exec chmod 0666 {} +
chown -R "$PUID:$PGID" /app/sessions /app/attached_assets
find /app/sessions /app/attached_assets -type d -exec chmod 0700 {} +
find /app/sessions /app/attached_assets -type f -exec chmod 0600 {} +

umask 000
exec gosu "$PUID:$PGID" "$@"
