import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app


class AppTests(unittest.TestCase):
    def test_settings_loads_sample_facility_and_excludes_underscore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'config.example.json').write_text(
                json.dumps({
                    'facility': 'sample',
                    'demo_mode': True,
                    'gemini': {'model': 'gemini-3.5-flash-lite'},
                    'external_apis': {'transit_plan': 'free'},
                    'mmd': {},
                    'coeiroink': {},
                }),
                encoding='utf-8',
            )
            docs = root / 'facilities' / 'sample' / 'docs'
            docs.mkdir(parents=True)
            (root / 'facilities' / 'sample' / 'facility.json').write_text(
                json.dumps({'name': 'サンプル施設', 'greeting': 'hi', 'persona': 'p', 'knowledge': []}),
                encoding='utf-8',
            )
            (docs / 'public.md').write_text('公開情報', encoding='utf-8')
            (docs / '_private.md').write_text('非公開情報', encoding='utf-8')
            with patch.object(app, 'ROOT', root):
                cfg, fac = app.settings()
        self.assertEqual(cfg['facility'], 'sample')
        self.assertEqual(fac['name'], 'サンプル施設')
        self.assertEqual([d['file'] for d in fac['documents']], ['public.md'])

    def test_sync_mmd_files_generates_fst_and_mdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = {
                'mmd': {
                    'model_alias': 'guide',
                    'model_path': 'assets/mmd/uka/MS_Uka.pmd',
                    'idle_motion': 'assets/mmd/gene/motion/stand.vmd',
                    'host': '127.0.0.1',
                    'port': 39391,
                    'window_size': '800,600',
                }
            }
            with patch.object(app, 'ROOT', root):
                app.sync_mmd_files(cfg)
                fst = (root / 'guide.fst').read_text(encoding='utf-8')
                mdf = (root / 'guide.mdf').read_text(encoding='utf-8')
            self.assertIn('MODEL_ADD|guide|assets/mmd/uka/MS_Uka.pmd', fst)
            self.assertIn('MOTION_ADD|guide|idle|assets/mmd/gene/motion/stand.vmd|FULL|LOOP', fst)
            self.assertIn('window_size=800,600', mdf)

    def test_safe_relpath_rejects_traversal(self):
        with self.assertRaises(ValueError):
            app.safe_relpath('../secret.pmd')

    def test_demo_respond_and_voice_failure_keeps_answer(self):
        cfg = {'facility': 'sample', 'demo_mode': True, 'mmd': {'enabled': False, 'model_alias': 'guide'}}
        fac = {'name': 'サンプル', 'knowledge': [{'question': '営業時間', 'answer': '開館時間は9時から17時です。'}]}
        with patch.object(app, 'settings', return_value=(cfg, fac)), \
             patch.object(app, 'synthesize', side_effect=OSError('no coeiroink')):
            result = app.respond('営業時間は？', voice=True)
        self.assertIn('開館時間', result['answer'])
        self.assertIsNone(result['audio'])
        self.assertTrue(result['warnings'])

    def test_thinking_stops_when_generation_fails(self):
        sent = []
        cfg, fac = app.settings()
        cfg['demo_mode'] = False
        cfg['mmd']['enabled'] = True
        with patch.object(app, 'settings', return_value=(cfg, fac)), \
             patch.object(app, 'mmd', side_effect=lambda c, m: sent.append(m)), \
             patch.object(app, 'answer', side_effect=ValueError('boom')):
            with self.assertRaises(ValueError):
                app.respond('テスト', voice=False)
        self.assertTrue(any(m.startswith('MOTION_ADD|') for m in sent))
        self.assertTrue(any(m.startswith('MOTION_DELETE|') for m in sent))

    def test_thinking_continues_during_synthesis_and_stops_after(self):
        events = []
        cfg, fac = app.settings()
        cfg['demo_mode'] = True
        cfg['mmd']['enabled'] = True

        def fake_mmd(_cfg, msg):
            events.append(msg)

        def fake_synth(_cfg, _text):
            events.append('SYNTHESIZE')
            raise OSError('skip wav write')

        with patch.object(app, 'settings', return_value=(cfg, fac)), \
             patch.object(app, 'mmd', side_effect=fake_mmd), \
             patch.object(app, 'synthesize', side_effect=fake_synth):
            app.respond('営業時間は？', voice=True)

        self.assertEqual(len(events), 3)
        self.assertTrue(events[0].startswith('MOTION_ADD|'))
        self.assertEqual(events[1], 'SYNTHESIZE')
        self.assertTrue(events[2].startswith('MOTION_DELETE|'))

    def test_mmd_audio_end_event_releases_wait(self):
        app.SPEECH_FINISHED.clear()
        app.SOUND_STARTED = False
        app.SPEAKING_UNTIL = 999999999
        app.mmd_event('SOUND_EVENT_START|__speak__guide')
        app.mmd_event('SOUND_EVENT_STOP|__speak__guide')
        result = app.wait_speech_end()
        self.assertEqual(result, {'speaking': False, 'ended_by': 'audio'})

    def test_post_retries_on_gemini_503(self):
        import io
        import urllib.error

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ok":true}'

        calls = {'n': 0}

        def fake_urlopen(_req, timeout=45):
            calls['n'] += 1
            if calls['n'] == 1:
                raise urllib.error.HTTPError('https://generativelanguage.googleapis.com/v1beta/models/x', 503, 'Unavailable', {}, io.BytesIO(b'{}'))
            return FakeResp()

        with patch('urllib.request.urlopen', side_effect=fake_urlopen), patch('time.sleep'):
            out = app.post('https://generativelanguage.googleapis.com/v1beta/models/x', {'a': 1})
        self.assertEqual(out, b'{"ok":true}')
        self.assertEqual(calls['n'], 2)

    def test_log_conversation_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = {'facility': 'test_01', 'demo_mode': False, 'logging': {'save_conversation': True}}
            res = {'answer': '9時から17時です。', 'warnings': [], 'timings': {'gemini': 0.5}}
            with patch.object(app, 'ROOT', root):
                app.log_conversation(cfg, '営業時間は？', res, mode='auto')
            files = list((root / 'runtime' / 'conversations').glob('*.jsonl'))
            self.assertEqual(len(files), 1)
            logged = json.loads(files[0].read_text(encoding='utf-8').strip())
            self.assertEqual(logged['facility'], 'test_01')
            self.assertEqual(logged['question'], '営業時間は？')
            self.assertEqual(logged['answer'], '9時から17時です。')


if __name__ == '__main__':
    unittest.main()
