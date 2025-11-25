  #!/bin/bash
  echo "=== Double BB  Strategy Status ==="
  PID=$(pgrep -f double_bb)
  if [ -n "$PID" ]; then
      echo "✅ Running (PID: $PID)"
      ps -p $PID -o pid,etime,cmd
  else
      echo "❌ Not running"
  fi
