#!/usr/bin/env bash
# Run a step script inside our container.
#
#   ./run.sh s1_ping.py                 one script
#   ./run.sh s2_read.py --baud 57600    arguments pass straight through
#   ./run.sh                            interactive shell, for poking around
#
# --rm means the container is deleted the moment it exits: nothing accumulates,
# nothing to clean up later.  The image is the only thing that persists, and
# `docker rmi dxl` removes that.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PORT="${DXL_PORT:-/dev/ttyACM0}"

if [ ! -e "$PORT" ]; then
  echo "no such device: $PORT"
  echo "what is there:"
  ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || echo "  no serial devices at all -- is the arm powered and plugged in?"
  exit 1
fi

# One wire, one talker.  If the vendor stack has the port open, we get
# "Device or resource busy" here rather than mysterious silence later.
if docker ps --format '{{.Names}}' | grep -q '^open_manipulator$'; then
  if docker exec open_manipulator sh -c "ps -eo args | grep -q '[r]os2_control_node'" 2>/dev/null; then
    echo "WARNING: ros2_control is running in the open_manipulator container."
    echo "         It holds $PORT.  Stop it first:"
    echo "         docker exec open_manipulator pkill -f '[r]os2_control_node'"
    echo
  fi
fi

if [ $# -eq 0 ]; then
  exec docker run --rm -it --device "$PORT" -v "$HERE:/work" dxl
fi

exec docker run --rm -it --device "$PORT" -v "$HERE:/work" dxl python3 "$@"
