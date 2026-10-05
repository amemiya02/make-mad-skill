#!/bin/bash
# analyze every validated corpus video once (metrics.json marks done)
HERE="$(cd "$(dirname "$0")" && pwd)"   # resolve before cd: $0 may be relative
cd "${CORPUS_DIR:-$(pwd)}"   # corpus working dir: ids.txt, videos/, study/
for id in $(cat fetch.log fetch-extra.log | grep '^OK ' | cut -d' ' -f2); do
  [ -f study/$id/metrics.json ] && [ study/$id/metrics.json -nt videos/$id.mp4 ] && continue
  "${PYTHON:-python3}" "$HERE/../analyze_mad.py" videos/$id.mp4 study/$id > study-$id.log 2>&1 && echo "done $id" || echo "fail $id"
done
