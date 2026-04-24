#!/bin/bash
#
# Hyper Scalper V2 트레이딩 중지
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

PID_FILE="$PROJECT_DIR/state/hyper.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "Hyper Scalper가 실행 중이 아닙니다 (PID 파일 없음)"
    exit 0
fi

PID=$(cat "$PID_FILE")

if ps -p "$PID" > /dev/null 2>&1; then
    echo "Hyper Scalper 중지 중... (PID: $PID)"
    kill "$PID"

    # 프로세스 종료 대기 (최대 10초)
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            echo "Hyper Scalper 중지 완료"
            rm -f "$PID_FILE"
            exit 0
        fi
        sleep 1
    done

    # 강제 종료
    echo "강제 종료 중..."
    kill -9 "$PID" 2>/dev/null
    rm -f "$PID_FILE"
    echo "Hyper Scalper 강제 종료 완료"
else
    echo "Hyper Scalper가 실행 중이 아닙니다 (프로세스 없음)"
    rm -f "$PID_FILE"
fi
