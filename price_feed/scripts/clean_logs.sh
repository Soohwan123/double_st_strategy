#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$(readlink -f "$SCRIPT_DIR/../logs")"
KEEP_COUNT=5
[ ! -d "$LOG_DIR" ] && exit 1
cd "$LOG_DIR" || exit 1
ls -1 price_feed_[0-9][0-9][0-9][0-9]-*.log 2>/dev/null | sort -r | tail -n +$((KEEP_COUNT + 1)) | xargs -r rm -f
