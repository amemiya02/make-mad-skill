"""No copyrighted media and no network calls. Run with unittest discovery."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mad',ROOT/'scripts/mad.py')
mad=importlib.util.module_from_spec(spec);spec.loader.exec_module(mad)

class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        (self.base/'source.mp4').touch();(self.base/'music.wav').touch()
        self.t=json.loads((ROOT/'templates/timeline.json').read_text())
        self.t['fps']='24';self.t['duration_frames']=120
        review={'native_quality':'pass','no_burned_subtitles':'pass','no_logos':'pass',
                'color_interpretation':'pass','evidence':'Synthetic unit fixture only','clean_ranges':[['0','20']]}
        self.t['assets']=[{'id':'v','kind':'video','path':'source.mp4','provenance':'synthetic',
                         'usage_basis':'self-created test fixture','review':copy.deepcopy(review)},
                        {'id':'a','kind':'audio','path':'music.wav','provenance':'synthetic',
                         'usage_basis':'self-created test fixture','review':copy.deepcopy(review)}]
        self.t['shots']=[{'id':'S1','asset_id':'v','source_in':'0','speed':'1','start_frame':0,
                         'duration_frames':60,'transition_in':{'type':'cut','duration_frames':0},
                         'narrative_function':'test A','sync_anchor':'test'},
                        {'id':'S2','asset_id':'v','source_in':'3','speed':'1','start_frame':60,
                         'duration_frames':60,'transition_in':{'type':'cut','duration_frames':0},
                         'narrative_function':'test B','sync_anchor':'test'}]
        self.t['audio']=[{'asset_id':'a','source_in':'0','start_frame':0,'duration_frames':120,
                         'gain_db':-6,'fade_in_frames':0,'fade_out_frames':12}]
        self.t['reviews']={k:'pass' for k in self.t['reviews']}
    def tearDown(self): self.tmp.cleanup()
    def check(self, final=False, inspect=False):
        return mad.validate_data(self.t,self.base,final=final,inspect=inspect)
    def invalid(self): self.assertFalse(self.check()['ok'])
    @staticmethod
    def meta(path,**kwargs):
        if path.suffix=='.wav': return {'streams':[{'codec_type':'audio','duration':'20'}],'format':{'duration':'20'}}
        return {'streams':[{'codec_type':'video','width':1920,'height':1080,'duration':'20',
                            'color_transfer':'bt709','field_order':'progressive'}],'format':{'duration':'20'}}
    def test_valid_cut_timeline(self): self.assertTrue(self.check()['ok'])
    def test_missing_asset(self): self.t['shots'][0]['asset_id']='missing';self.invalid()
    def test_missing_path(self): self.t['assets'][0]['path']='absent.mp4';self.invalid()
    def test_duplicate_asset(self): self.t['assets'].append(self.t['assets'][0]);self.invalid()
    def test_duplicate_shot(self): self.t['shots'][1]['id']='S1';self.invalid()
    def test_gap_rejected(self): self.t['shots'][1]['start_frame']=61;self.invalid()
    def test_overlap_rejected(self): self.t['shots'][1]['start_frame']=59;self.invalid()
    def test_empty_movie_rejected(self): self.t['shots']=[];self.invalid()
    def test_total_mismatch(self): self.t['duration_frames']=121;self.invalid()
    def test_no_sound_rejected(self): self.t['audio']=[];self.invalid()
    def test_sound_overrun(self): self.t['audio'][0]['duration_frames']=121;self.invalid()
    def test_fade_overrun(self): self.t['audio'][0]['fade_in_frames']=119;self.invalid()
    def test_unknown_effect_rejected(self): self.t['shots'][0]['ai_transition']='magic';self.invalid()
    def test_speed_range(self): self.t['shots'][0]['speed']='9';self.invalid()
    def test_invalid_rational(self): self.t['fps']='24/0';self.invalid()
    def test_negative_source(self): self.t['shots'][0]['source_in']='-1';self.invalid()
    def test_nonzero_first(self): self.t['shots'][0]['start_frame']=1;self.invalid()
    def test_zero_fps(self): self.t['fps']='0';self.invalid()
    def test_cut_with_dissolve_length(self): self.t['shots'][0]['transition_in']['duration_frames']=6;self.invalid()
    def test_valid_dissolve_math(self):
        self.t['shots'][1]['transition_in']={'type':'dissolve','duration_frames':12}
        self.t['shots'][1]['start_frame']=48;self.t['duration_frames']=108;self.t['audio'][0]['duration_frames']=108
        self.assertTrue(self.check()['ok'])
    def test_entire_shot_dissolve(self):
        self.t['shots'][1]['transition_in']={'type':'dissolve','duration_frames':60}
        self.t['shots'][1]['start_frame']=0;self.invalid()
    def test_final_pending_story(self):
        self.t['reviews']['story']='pending';self.assertFalse(self.check(final=True)['ok'])
    def test_source_metadata_full_pass(self):
        with patch.object(mad,'probe',self.meta): self.assertTrue(self.check(final=True,inspect=True)['ok'])
    def test_unreviewed_source_blocked(self):
        self.t['assets'][0]['review']['no_logos']='pending'
        with patch.object(mad,'probe',self.meta): self.assertFalse(self.check(final=True,inspect=True)['ok'])
    def test_clean_range_missing(self):
        self.t['assets'][0]['review']['clean_ranges']=[['0','1']]
        with patch.object(mad,'probe',self.meta): self.assertFalse(self.check(final=True,inspect=True)['ok'])
    def test_720p_source_blocked(self):
        def low(p,**kw):
            m=self.meta(p)
            if p.suffix=='.mp4': m['streams'][0].update(width=1280,height=720)
            return m
        with patch.object(mad,'probe',low): self.assertFalse(self.check(final=True,inspect=True)['ok'])
    def test_hdr_blocked(self):
        def hdr(p,**kw):
            m=self.meta(p)
            if p.suffix=='.mp4':m['streams'][0]['color_transfer']='smpte2084'
            return m
        with patch.object(mad,'probe',hdr): self.assertFalse(self.check(inspect=True)['ok'])
    def test_source_overrun(self):
        self.t['shots'][0]['source_in']='19'
        with patch.object(mad,'probe',self.meta): self.assertFalse(self.check(inspect=True)['ok'])
    def test_precomp_lineage_missing(self):
        self.t['assets'][0]['kind']='precomp'
        with patch.object(mad,'probe',self.meta): self.assertFalse(self.check(final=True,inspect=True)['ok'])
    def test_video_camera_move_rejected(self):
        self.t['shots'][0]['motion']={'zoom_start':1,'zoom_end':1.1,'x_start':.5,'x_end':.5,'y_start':.5,'y_end':.5}
        self.invalid()
    def test_exact_fraction(self): self.assertEqual(mad.frame_seconds(24000,'24000/1001'),1001)
    def test_absolute_beat_rounding(self):
        for i in range(10000):
            t=mad.frac(i)/7;r=mad.nearest_frame(t,'24000/1001')
            self.assertLessEqual(abs(mad.frac(r)-t*mad.frac('24000/1001')),mad.frac('1/2'))
    def test_contact_excludes_fractional_tail(self):
        self.assertEqual(mad.contact_times(6.006,2,4,mad.frac('24000/1001')),[0,2,4])
    def test_contact_short_clip(self):
        self.assertEqual(mad.contact_times(.02,2,4,mad.frac('24')),[0])
    def test_contact_regular_grid(self):
        self.assertEqual(mad.contact_times(8,2,4,mad.frac('24')),[0,2,4,6])
    def test_half_up(self): self.assertEqual(mad.nearest_frame('1/48','24'),1)
    def test_negative_time_rejected(self):
        with self.assertRaises(mad.MadError): mad.nearest_frame('-1','24')
    def test_network_timeline_rejected(self):
        with self.assertRaises(mad.MadError): mad.media_path(self.base,'https://example.com/v.mp4')
    def test_private_download_rejected(self):
        with patch.object(mad.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(mad.MadError):mad.check_public_https('https://test.example/file')
    def test_http_download_rejected(self):
        with self.assertRaises(mad.MadError):mad.check_public_https('http://example.com/file')
    def test_init_creates_project(self):
        d=self.base/'project'
        result=mad.init_project(d,'Test project','24000/1001')
        self.assertEqual(result['status'],'BRIEF')
        self.assertTrue((d/'edit/timeline.json').is_file())
        self.assertTrue((d/'analysis/brief.md').is_file())
        self.assertEqual(mad.read_json(d/'edit/timeline.json')['fps'],'24000/1001')
    def test_init_preserves_nonempty_directory(self):
        d=self.base/'existing';d.mkdir();f=d/'keep.txt';f.write_text('keep me')
        with self.assertRaises(mad.MadError):mad.init_project(d,'Do not overwrite','24')
        self.assertEqual(f.read_text(),'keep me')
    def test_empty_template_not_renderable(self):
        t=json.loads((ROOT/'templates/timeline.json').read_text())
        self.assertFalse(mad.validate_data(t,self.base,inspect=False)['ok'])

if __name__=='__main__':unittest.main(verbosity=2)
