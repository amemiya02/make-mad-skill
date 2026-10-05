"""harvest MAD candidates from Bilibili search API (MAD·AMV zone tid 24), rank by quality signals."""
import json, time, urllib.request, urllib.parse, http.cookiejar, sys
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
H = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36', 'Referer': 'https://www.bilibili.com/'}
def get(u):
    return json.loads(op.open(urllib.request.Request(u, headers=H), timeout=20).read().decode())
op.open(urllib.request.Request('https://www.bilibili.com/', headers=H), timeout=20).read()
spi = get('https://api.bilibili.com/x/frontend/finger/spi')['data']
for k, v in (('buvid3', spi['b_3']), ('buvid4', spi['b_4'])):
    cj.set_cookie(http.cookiejar.Cookie(0, k, v, None, False, '.bilibili.com', True, True, '/', True, False, None, False, None, None, {}))
out = {}
for kw in sys.argv[1:]:
    for order in ('click', 'stow'):
        for page in (1, 2):
            q = urllib.parse.urlencode({'search_type': 'video', 'keyword': kw, 'order': order, 'tids': 24, 'page': page})
            try:
                d = get('https://api.bilibili.com/x/web-interface/search/type?' + q)
            except Exception as e:
                print('ERR', kw, order, e, file=sys.stderr); continue
            for r in (d.get('data') or {}).get('result') or []:
                out[r['bvid']] = dict(bvid=r['bvid'], title=r['title'].replace('<em class="keyword">', '').replace('</em>', ''),
                                      author=r['author'], play=r['play'], fav=r['favorites'], dur=r['duration'], kw=kw, pub=r['pubdate'])
            time.sleep(0.6)
json.dump(out, open('cands-raw.json', 'w'), ensure_ascii=False, indent=0)
print(len(out))
