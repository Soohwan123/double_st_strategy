#!/bin/bash

# 1. 스크립트 파일이 실제 위치한 경로를 절대 경로로 획득
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 2. 스크립트 위치 기준으로 ../logs 경로를 절대 경로로 변환
LOG_DIR="$(readlink -f "$SCRIPT_DIR/../logs")"
KEEP_COUNT=5

# 디렉토리 존재 여부 확인 (안전장치)
if [ ! -d "$LOG_DIR" ]; then
    echo "Error: Directory $LOG_DIR does not exist." >> "$SCRIPT_DIR/cleanup_error.log"
    exit 1
fi

cd "$LOG_DIR" || exit 1

# 삭제 패턴
PATTERNS=("hyper_v2_[0-9][0-9][0-9][0-9]-*.log")

for PATTERN in "${PATTERNS[@]}"; do
    # 최신 5개를 제외하고 삭제
    ls -1 $PATTERN 2>/dev/null | sort -r | tail -n +$((KEEP_COUNT + 1)) | xargs -r rm -f
done
