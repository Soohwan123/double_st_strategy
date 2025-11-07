  #!/bin/bash
  echo "=== Double ST Strategy Status ==="
  PID=$(pgrep -f double_st_strategy_live)
  if [ -n "$PID" ]; then
      echo "✅ Running (PID: $PID)"
      ps -p $PID -o pid,etime,cmd
  else
      echo "❌ Not running"
  fi
