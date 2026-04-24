#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$(readlink -f "$SCRIPT_DIR/../logs")"
KEEP_COUNT=5

if [ ! -d "$LOG_DIR" ]; then
    echo "Error: Directory $LOG_DIR does not exist." >> "$SCRIPT_DIR/cleanup_error.log"
    exit 1
fi

cd "$LOG_DIR" || exit 1

PATTERNS=("eth_hyper_[0-9][0-9][0-9][0-9]-*.log")

for PATTERN in "${PATTERNS[@]}"; do
    ls -1 $PATTERN 2>/dev/null | sort -r | tail -n +$((KEEP_COUNT + 1)) | xargs -r rm -f
done
