#!/bin/bash
set -e

cd /opt/cicero

case "$1" in
  orders)
    exec python fairdiplomacy_external/run.py --adhoc \
      --cfg conf/c07_play_webdip/play_cicero_full_test.prototxt \
      webdip_url="http://webserver"
    ;;
  dialogue)
    exec python claude_dialogue_bot.py
    ;;
  *)
    exec "$@"
    ;;
esac
