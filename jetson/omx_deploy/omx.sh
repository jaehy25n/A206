#!/usr/bin/env bash
# Host-side helper around docker compose for the OMX control container.
set -e
cd "$(dirname "$0")"

compose() {
  if docker compose version >/dev/null 2>&1; then docker compose "$@"; else docker-compose "$@"; fi
}

case "${1:-help}" in
  init)
    printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" > .env
    mkdir -p "$HOME/omx_recordings"
    compose build
    ;;
  up)     compose up -d ;;
  build)
    shift
    sel=""; [ $# -gt 0 ] && sel="--packages-select $*"
    compose exec control bash -lc "cd /ws && colcon build --symlink-install $sel"
    ;;
  shell)  compose exec control bash ;;
  run)    shift; compose exec control bash -lc "$*" ;;
  down)   compose down ;;
  logs)   compose logs -f ;;
  *)
    cat <<USAGE
usage: $0 <command>
  init            write .env (host UID/GID), create ~/omx_recordings, build the image
  up              start the control container (idle) in the background
  build [pkgs..]  colcon build --symlink-install inside the container
  shell           interactive shell inside the container (ROS + workspace sourced)
  run <cmd..>     run one command inside the container, e.g. ./omx.sh run ros2 topic list
  down            stop and remove the container
  logs            follow container logs
USAGE
    ;;
esac
