#!/usr/bin/env python3
"""Prepare acquisition searches and record actual downloads; never invent results.

Searches are executed by the host agent/browser. Downloads use the provider's
normal export, mad.py fetch, or optional yt-dlp/aria2 as documented in references.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import urllib.parse

try:
    from . import mad
except ImportError:
    import mad

ROOT = Path(__file__).resolve().parents[1]


def strings(value, field):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise mad.MadError(f'{field} must be a list of non-empty strings')
    return list(dict.fromkeys(x.strip() for x in value))


def web_query(query):
    return 'https://www.google.com/search?' + urllib.parse.urlencode({'q': query})


def write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def plan(brief_path: Path, output: Path):
    brief = mad.read_json(brief_path)
    music = brief.get('music', {})
    anime = brief.get('anime', [])
    if not isinstance(music, dict) or not isinstance(anime, list):
        raise mad.MadError('music must be an object and anime must be a list')
    if not isinstance(brief.get('community_indexes', True), bool):
        raise mad.MadError('community_indexes must be true or false')
    themes = strings(music.get('keywords', []), 'music.keywords')
    locked = music.get('locked_track', {})
    if not isinstance(locked, dict) or any(not isinstance(locked.get(k, ''), str) for k in ['title', 'artist', 'version']):
        raise mad.MadError('locked_track must contain string title, artist and version')
    locked_query = ' '.join(locked.get(k, '').strip() for k in ['artist', 'title', 'version']).strip()
    queries = [locked_query] if locked.get('title', '').strip() else themes
    jobs, coverage, seen = [], [], set()

    def add(kind, work_id, episode, provider, query, url):
        jobs.append(dict(job_id=f'Q{len(jobs)+1:04d}', kind=kind, work_id=work_id,
                         episode=episode, provider=provider, query=query, url=url,
                         status='planned', checked_at='', result_evidence=''))

    for query in queries:
        for provider, domain in [('artist-store', 'bandcamp.com'), ('artist-download', 'soundcloud.com'),
                                 ('opentracks', 'opentracks.com'), ('bgmer', 'bgmer.net'), ('musmus', 'musmus.main.jp')]:
            q = f'site:{domain} {query}'
            add('music', 'bgm', '', provider, q, web_query(q))
        add('music', 'bgm', '', 'youtube-audio-library', query, 'https://www.youtube.com/audiolibrary')
        if locked.get('title', '').strip():
            q = f'{query} official artist label download'
            add('music', 'bgm', '', 'official-recording', q, web_query(q))

    for item in anime:
        if not isinstance(item, dict):
            raise mad.MadError('Each anime entry must be an object')
        ident = item.get('id', '')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', ident) or ident in seen:
            raise mad.MadError('Anime ids must be unique lowercase identifiers')
        seen.add(ident)
        titles = strings(item.get('titles', []), f'{ident}.titles')
        if not titles:
            raise mad.MadError(f'{ident} needs at least one confirmed title/alias')
        season = item.get('season', '')
        if not isinstance(season, str) or not season.strip():
            raise mad.MadError(f'{ident} needs an explicit season/version label (e.g. S01, movie)')
        episodes = strings(item.get('episodes', []), f'{ident}.episodes')
        if any(not re.fullmatch(r'[A-Za-z0-9._-]+', e) for e in episodes):
            raise mad.MadError('Use explicit episode identifiers, not a prose list or a range')
        if any(re.fullmatch(r'\d+-\d+', e) for e in episodes):
            raise mad.MadError('Expand episode ranges into separate identifiers')
        for episode in episodes or ['']:
            coverage.append(dict(work_id=ident, title=titles[0], season=season,
                                 episode=episode, status='not_searched' if episode else 'needs_episode_mapping',
                                 selected_candidate='', local_path='', receipt='', clean_review='', blocker=''))
            for title in titles:
                q = f'"{title}" {season} {episode} Blu-ray 収録 公式'
                add('anime', ident, episode, 'official-release', q, web_query(q))
                # Season numbering is checked on the release page: filenames often omit it.
                q = ' '.join(x for x in [title, episode, '1080p'] if x)
                if brief.get('community_indexes', True):
                    for provider, category in [('nyaa-raw', '1_4'), ('nyaa-softsub-candidate', '1_2')]:
                        url = 'https://nyaa.si/?' + urllib.parse.urlencode({'f': '0', 'c': category, 'q': q})
                        add('anime', ident, episode, provider, q, url)
                    add('anime', ident, episode, 'animetosho', q,
                        'https://animetosho.org/search?' + urllib.parse.urlencode({'q': q}))
        for title in titles:
            if brief.get('community_indexes', True):
                for provider, domain in [('erai-raws', 'erai-raws.info'), ('subsplease', 'subsplease.org')]:
                    q = f'site:{domain} "{title}" 1080p'
                    add('anime', ident, '', provider, q, web_query(q))
            for suffix in ['1080p BDRip', '1080p WEB-DL', 'NCOP NCED creditless']:
                q = f'"{title}" {suffix}'
                add('anime', ident, '', 'release-search', q, web_query(q))
    if not jobs:
        raise mad.MadError('Provide music keywords/a locked title or at least one anime')
    if output.exists() and any(output.iterdir()):
        raise mad.MadError('Refusing to overwrite a non-empty acquisition directory')
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output/'search-jobs.csv', list(jobs[0]), jobs)
    write_csv(output/'anime-coverage.csv', ['work_id','title','season','episode','status',
              'selected_candidate','local_path','receipt','clean_review','blocker'], coverage)
    for name in ['music-shortlist.csv', 'source-candidates.csv']:
        shutil.copy2(ROOT/'templates'/name, output/name)
    mad.write_json(output/'brief.json', brief)
    result = {'status': 'planned_not_searched', 'search_jobs': len(jobs),
              'episode_requirements': len(coverage), 'anime_titles': len(anime),
              'unresolved_episode_mappings': sum(not r['episode'] for r in coverage),
              'output': str(output.resolve())}
    mad.write_json(output/'plan.json', result)
    return result


def record(media: Path, manifest: Path, output: Path):
    request = mad.read_json(manifest)
    if request.get('kind') not in ('audio', 'video'):
        raise mad.MadError('kind must be audio or video')
    for field in ['provenance', 'usage_basis', 'retrieval_method']:
        if not isinstance(request.get(field), str) or not request[field].strip():
            raise mad.MadError(f'Download record requires {field}')
    if request['retrieval_method'] not in ('browser', 'https-direct', 'yt-dlp', 'torrent', 'user-local'):
        raise mad.MadError('Unsupported retrieval_method')
    if request.get('download_authorized') is not True:
        raise mad.MadError('Record the existing download authorization; do not fabricate it')
    if request['retrieval_method'] != 'user-local':
        page = urllib.parse.urlsplit(request.get('source_page', ''))
        if page.scheme != 'https' or not page.hostname or page.username or page.password:
            raise mad.MadError('An HTTPS source_page without embedded credentials is required')
    expected = request.get('expected_sha256', '')
    if expected and (not isinstance(expected, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected)):
        raise mad.MadError('expected_sha256 must be a trusted SHA256 or omitted')
    if not media.is_file() or media.stat().st_size == 0 or output.exists():
        raise mad.MadError('A non-empty media file and a new receipt path are required')
    if media.suffix.lower() in ('.part', '.aria2', '.torrent'):
        raise mad.MadError('Download control/partial files are not media')
    if Path(str(media)+'.aria2').exists():
        raise mad.MadError('aria2 control file remains; verify download completion before recording')
    digest = mad.sha(media)
    if expected and digest.lower() != expected.lower():
        raise mad.MadError('Downloaded SHA256 mismatch')
    meta = mad.probe(media)
    kind = request['kind']
    streams = [s for s in meta.get('streams', []) if s.get('codec_type') == kind
               and not s.get('disposition', {}).get('attached_pic')]
    duration = mad.media_duration(meta, kind)
    if not streams or not math.isfinite(duration) or duration <= 0:
        raise mad.MadError(f'No usable {kind} stream/duration')
    if kind == 'video' and (streams[0].get('width', 0) < 1920 or streams[0].get('height', 0) < 1080):
        raise mad.MadError('Video fails the >=1920x1080 raster gate')
    result = {'status': 'file_recorded_human_review_required',
              'recorded_at': datetime.now(timezone.utc).isoformat(), 'output': str(media.resolve()),
              'bytes': media.stat().st_size, 'sha256': digest,
              'hash_independently_verified': bool(expected), 'source_manifest': request, 'probe': meta,
              'review': {'identity_version_episode': 'pending', 'native_quality': 'pending',
                         'clean_ranges': [], 'no_burned_subtitles': 'pending' if kind == 'video' else 'not_applicable',
                         'no_logos': 'pending' if kind == 'video' else 'not_applicable',
                         'playback_or_listening': 'pending', 'usage_scope': 'declared_not_independently_verified'}}
    mad.write_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan'); p.add_argument('brief', type=Path); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('record'); p.add_argument('input', type=Path); p.add_argument('--manifest', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    a = parser.parse_args()
    try:
        result = plan(a.brief, a.out) if a.command == 'plan' else record(a.input, a.manifest, a.out)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (mad.MadError, OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f'make-mad sources: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
