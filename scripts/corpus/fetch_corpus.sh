#!/bin/bash
# download each corpus video, validate stream durations against info.json, retry up to 4 times
HERE="$(cd "$(dirname "$0")" && pwd)"   # resolve before cd: $0 may be relative
cd "${CORPUS_DIR:-$(pwd)}"   # corpus working dir: ids.txt, videos/, study/
ok() {  # $1 = id : every stream within 1.5 s of the declared duration
  [ -f videos/$1.mp4 ] || return 1
  want=$("${PYTHON:-python3}" -c "import json;print(json.load(open('videos/$1.info.json'))['duration'])" 2>/dev/null) || return 1
  ffprobe -v error -show_entries stream=duration -of csv=p=0 videos/$1.mp4 | awk -v w=$want 'BEGIN{r=0} {if ($1 < w-1.5) r=1} END{exit r}'
}
for id in $(cat ids.txt); do
  for try in 1 2 3 4; do
    ok $id && break
    rm -f videos/$id.mp4 videos/$id.f*.mp4* videos/$id.f*.m4a*
    yt-dlp --no-warnings -q --retries 10 --fragment-retries 10 --http-chunk-size 4M \
      -f "bv*[height<=480][vcodec^=avc1]+ba/bv*[height<=480]+ba/b" --merge-output-format mp4 \
      -o "videos/$id.%(ext)s" --write-info-json "https://www.bilibili.com/video/$id/" 2>>dl.log
  done
  ok $id && echo "OK $id" || echo "FAIL $id"
done
