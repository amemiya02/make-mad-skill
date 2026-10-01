"""Acquisition contract tests: synthetic metadata and mock HTTPS, no external media."""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import sources
mad = sources.mad


def meta(kind='audio', width=1920, height=1080):
    stream = {'codec_type': kind, 'duration': '6'}
    if kind == 'video':
        stream.update(width=width, height=height)
    return {'streams': [stream], 'format': {'duration': '6'}}


class Acquisition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.brief = {'music': {'keywords': ['切ない ピアノ', 'post rock crescendo']},
                      'anime': [{'id': 'work-a', 'titles': ['日本語の作品', 'English Alias'],
                                 'season': 'S01 TV 2023', 'episodes': ['01', '02']},
                                {'id': 'work-b', 'titles': ['Other Movie'],
                                 'season': 'movie 2024', 'episodes': ['movie']}]}
        self.media = self.base/'original.bin'
        self.media.write_bytes(b'Original synthetic test data')
        self.record_request = {'kind': 'audio', 'retrieval_method': 'user-local',
                               'download_authorized': True, 'provenance': 'Synthetic unit fixture',
                               'usage_basis': 'Created for this test'}
    def tearDown(self):
        self.tmp.cleanup()
    def manifest(self, data, name='request.json'):
        path = self.base/name
        path.write_text(json.dumps(data), encoding='utf-8')
        return path
    def plan(self):
        directory = self.base/'plan'
        result = sources.plan(self.manifest(self.brief), directory)
        def rows(name):
            with (directory/name).open(encoding='utf-8-sig', newline='') as f:
                return list(csv.DictReader(f))
        return result, rows('search-jobs.csv'), rows('anime-coverage.csv')
    def record(self, probe_meta=None):
        with patch.object(mad, 'probe', return_value=probe_meta or meta()):
            return sources.record(self.media, self.manifest(self.record_request), self.base/'receipt.json')

    def test_each_required_episode_has_coverage_and_search_evidence_is_empty(self):
        result, jobs, coverage = self.plan()
        self.assertEqual({(r['work_id'], r['episode']) for r in coverage},
                         {('work-a', '01'), ('work-a', '02'), ('work-b', 'movie')})
        self.assertEqual(result['episode_requirements'], 3)
        self.assertEqual(result['status'], 'planned_not_searched')
        self.assertTrue(all(j['status'] == 'planned' and not j['result_evidence'] for j in jobs))
        self.assertTrue(any('%E6%97%A5' in j['url'] for j in jobs))
        self.assertTrue(any('c=1_4' in j['url'] for j in jobs))
        self.assertTrue(any('c=1_2' in j['url'] for j in jobs))
    def test_locked_track_does_not_become_unrelated_music_search(self):
        self.brief['music']['locked_track'] = {'artist': 'Artist X', 'title': 'Exact Track', 'version': 'album mix'}
        _, jobs, _ = self.plan()
        music = [j for j in jobs if j['kind'] == 'music']
        self.assertTrue(all('Artist X Exact Track album mix' in j['query'] for j in music))
        self.assertFalse(any('post rock' in j['query'] for j in music))
    def test_unknown_episode_is_unresolved_not_fabricated(self):
        self.brief['anime'][0]['episodes'] = []
        result, _, coverage = self.plan()
        unknown = next(r for r in coverage if r['work_id'] == 'work-a')
        self.assertEqual(unknown['status'], 'needs_episode_mapping')
        self.assertEqual(unknown['episode'], '')
        self.assertEqual(result['unresolved_episode_mappings'], 1)
    def test_community_indexes_can_be_excluded(self):
        self.brief['community_indexes'] = False
        _, jobs, _ = self.plan()
        self.assertFalse(any(j['provider'] in ['nyaa-raw','nyaa-softsub-candidate','animetosho','erai-raws','subsplease'] for j in jobs))
        self.assertTrue(any(j['provider'] == 'official-release' for j in jobs))
    def test_plan_refuses_overwrite_without_losing_existing_evidence(self):
        directory = self.base/'plan'
        directory.mkdir()
        keep = directory/'search-jobs.csv'
        keep.write_text('Actual results already here')
        with self.assertRaises(mad.MadError):
            sources.plan(self.manifest(self.brief), directory)
        self.assertEqual(keep.read_text(), 'Actual results already here')
    def test_ambiguous_or_invalid_episode_requirements_are_rejected(self):
        for replacement in [{'episodes':['01-03']}, {'episodes':['episode one']}, {'season':''}, {'id':'../outside'}, {'titles':[]}]:
            with self.subTest(replacement=replacement):
                brief = copy.deepcopy(self.brief)
                brief['anime'][0].update(replacement)
                with self.assertRaises(mad.MadError):
                    sources.plan(self.manifest(brief), self.base/'bad-plan')
        brief = copy.deepcopy(self.brief)
        brief['anime'][1]['id'] = 'work-a'
        with self.assertRaises(mad.MadError):
            sources.plan(self.manifest(brief), self.base/'bad-plan')
    def test_empty_requirements_do_not_create_fake_results(self):
        with self.assertRaises(mad.MadError):
            sources.plan(self.manifest({}), self.base/'plan')
        self.assertFalse((self.base/'plan').exists())
    def test_audio_receipt_records_hash_but_preserves_listening_and_identity_review(self):
        result = self.record()
        self.assertEqual(result['sha256'], hashlib.sha256(self.media.read_bytes()).hexdigest())
        self.assertFalse(result['hash_independently_verified'])
        self.assertEqual(result['review']['playback_or_listening'], 'pending')
        self.assertEqual(result['review']['identity_version_episode'], 'pending')
        self.assertEqual(result['review']['no_burned_subtitles'], 'not_applicable')
    def test_softsub_video_receipt_does_not_certify_clean_source(self):
        self.record_request.update(kind='video', expected_sha256=mad.sha(self.media))
        metadata = meta('video')
        metadata['streams'].append({'codec_type':'subtitle', 'codec_name':'ass'})
        result = self.record(metadata)
        self.assertTrue(result['hash_independently_verified'])
        self.assertEqual(result['review']['no_burned_subtitles'], 'pending')
        self.assertEqual(result['review']['native_quality'], 'pending')
        self.assertEqual(result['review']['clean_ranges'], [])
    def test_wrong_stream_or_unknown_duration_is_not_a_download_receipt(self):
        for metadata in [meta('video'), {'streams':[], 'format':{'duration':'6'}},
                         {'streams':[{'codec_type':'audio'}], 'format':{'duration':'nan'}}]:
            with self.subTest(metadata=metadata):
                with self.assertRaises(mad.MadError):
                    self.record(metadata)
                self.assertFalse((self.base/'receipt.json').exists())
    def test_720p_and_cover_art_are_not_1080p_footage(self):
        self.record_request['kind'] = 'video'
        for metadata in [meta('video',1280,720),
                         {'streams':[{'codec_type':'video','width':1920,'height':1080,'disposition':{'attached_pic':1}}], 'format':{'duration':'6'}}]:
            with self.subTest(metadata=metadata):
                with self.assertRaises(mad.MadError):
                    self.record(metadata)
    def test_mismatching_expected_hash_stops_before_media_probe(self):
        self.record_request['expected_sha256'] = '0'*64
        with patch.object(mad, 'probe') as probe:
            with self.assertRaises(mad.MadError):
                sources.record(self.media, self.manifest(self.record_request), self.base/'receipt.json')
            probe.assert_not_called()
    def test_receipt_refuses_partial_media_and_aria2_control_files(self):
        for extension in ['.part','.torrent','.aria2']:
            path = self.base/('control'+extension)
            path.write_bytes(b'Not completed media')
            with self.assertRaises(mad.MadError):
                sources.record(path, self.manifest(self.record_request), self.base/'receipt.json')
        Path(str(self.media)+'.aria2').write_bytes(b'incomplete')
        with self.assertRaises(mad.MadError):
            self.record()
    def test_receipt_requires_download_attestation_and_credential_free_origin(self):
        for update in [{'download_authorized':False}, {'retrieval_method':'unknown'},
                       {'retrieval_method':'browser','source_page':'http://example.com/file'},
                       {'retrieval_method':'browser','source_page':'https://user:secret@example.com/file'},
                       {'kind':'unknown'}, {'usage_basis':''}]:
            with self.subTest(update=update):
                request = dict(self.record_request, **update)
                with self.assertRaises(mad.MadError):
                    sources.record(self.media, self.manifest(request), self.base/'receipt.json')
    def test_receipt_preserves_preexisting_output(self):
        out = self.base/'receipt.json'
        out.write_text('Existing reviewed receipt')
        with self.assertRaises(mad.MadError):
            sources.record(self.media, self.manifest(self.record_request), out)
        self.assertEqual(out.read_text(), 'Existing reviewed receipt')


class DirectDownloads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.output = self.base/'download.bin'
        self.payload = b'Synthetic direct-download bytes'
        self.request = {'kind':'audio', 'url':'https://example.com/media', 'download_authorized':True,
                        'provenance':'Synthetic mocked HTTPS fixture', 'usage_basis':'Self-created test bytes'}
    def tearDown(self):
        self.tmp.cleanup()
    def fetch(self, metadata=None, payload=None, headers=None):
        manifest = self.base/'download.json'
        manifest.write_text(json.dumps(self.request))
        response = io.BytesIO(self.payload if payload is None else payload)
        response.headers = {} if headers is None else headers
        opener = Mock()
        opener.open.return_value = response
        with patch.object(mad, 'check_public_https'), patch.object(mad.urllib.request, 'build_opener', return_value=opener), patch.object(mad, 'probe', return_value=metadata or meta()):
            return mad.fetch(manifest, self.output, 1)
    def assert_no_download(self):
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.base.glob('mad-download-*.part')))
        self.assertFalse(self.output.with_suffix('.bin.source.json').exists())
    def test_audio_download_writes_actual_bytes_and_unreviewed_sidecar(self):
        result = self.fetch()
        self.assertEqual(self.output.read_bytes(), self.payload)
        self.assertEqual(result['clean_source_status'], 'unreviewed')
        self.assertEqual(result['probe']['streams'][0]['codec_type'], 'audio')
        self.assertFalse(result['hash_independently_verified'])
        self.assertTrue(self.output.with_suffix('.bin.source.json').exists())
    def test_1080p_download_with_trusted_hash(self):
        self.request.update(kind='video', expected_sha256=hashlib.sha256(self.payload).hexdigest())
        result = self.fetch(meta('video'))
        self.assertTrue(result['hash_independently_verified'])
    def test_unknown_kind_is_rejected_before_network(self):
        self.request['kind'] = 'webpage'
        with self.assertRaises(mad.MadError):
            self.fetch()
        self.assert_no_download()
    def test_no_audio_stream_or_duration_cannot_pass_audio_download(self):
        for metadata in [meta('video'), {'streams':[{'codec_type':'audio'}], 'format':{'duration':'0'}},
                         {'streams':[{'codec_type':'audio'}], 'format':{'duration':'nan'}}]:
            with self.subTest(metadata=metadata):
                with self.assertRaises(mad.MadError):
                    self.fetch(metadata)
                self.assert_no_download()
    def test_720p_download_is_rejected_and_temporary_bytes_removed(self):
        self.request['kind'] = 'video'
        with self.assertRaises(mad.MadError):
            self.fetch(meta('video',1280,720))
        self.assert_no_download()
    def test_hash_mismatch_is_rejected_and_temporary_bytes_removed(self):
        self.request['expected_sha256'] = '0'*64
        with self.assertRaises(mad.MadError):
            self.fetch()
        self.assert_no_download()
    def test_size_limit_applies_to_header_and_streamed_bytes(self):
        for payload, headers in [(b'x',{'Content-Length':str(2*1024*1024)}), (b'x'*(1024*1024+1),{})]:
            with self.subTest(headers=headers):
                with self.assertRaises(mad.MadError):
                    self.fetch(payload=payload, headers=headers)
                self.assert_no_download()
    def test_existing_media_and_receipt_are_preserved(self):
        for path in [self.output, self.output.with_suffix('.bin.source.json')]:
            path.write_text('Existing evidence')
            with self.assertRaises(mad.MadError):
                self.fetch()
            self.assertEqual(path.read_text(), 'Existing evidence')
            path.unlink()
    def test_unapproved_download_is_rejected_without_output(self):
        self.request['download_authorized'] = False
        with self.assertRaises(mad.MadError):
            self.fetch()
        self.assert_no_download()


if __name__ == '__main__':
    unittest.main(verbosity=2)
