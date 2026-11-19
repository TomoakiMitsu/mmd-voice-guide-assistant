import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
import setup_wizard


class SetupWizardTests(unittest.TestCase):
    def test_apply_setup_creates_new_facility_and_updates_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_docs = root / 'facilities' / 'sample' / 'docs'
            sample_docs.mkdir(parents=True)
            (root / 'facilities' / 'sample' / 'facility.json').write_text(
                json.dumps({'name': 'sample', 'greeting': 'hi', 'persona': 'p', 'knowledge': [], 'notes': ''}),
                encoding='utf-8',
            )
            (root / 'config.example.json').write_text(
                json.dumps({
                    'facility': 'sample',
                    'demo_mode': True,
                    'gemini': {'model': 'gemini-3.5-flash-lite', 'max_output_tokens': 512, 'enable_google_search': True},
                    'external_apis': {'weather_enabled': True, 'transit_enabled': True, 'transit_plan': 'free'},
                    'mmd': {'enabled': False, 'connection': 'client', 'host': '127.0.0.1', 'port': 39391,
                            'model_alias': 'guide', 'model_path': 'assets/mmd/gene/Gene.pmd',
                            'idle_motion': '', 'thinking_motion': '', 'window_size': '900,720', 'credit': ''},
                    'coeiroink': {'url': 'http://127.0.0.1:50032', 'speaker_uuid': 'u', 'style_id': 0, 'speed': 1.1, 'credit': ''},
                }),
                encoding='utf-8',
            )
            (root / 'assets' / 'mmd' / 'uka' / 'motion').mkdir(parents=True)
            (root / 'assets' / 'mmd' / 'uka' / 'MS_Uka.pmd').write_bytes(b'pmd')
            (root / 'assets' / 'mmd' / 'uka' / 'motion' / 'stand.vmd').write_bytes(b'vmd')

            with patch.object(setup_wizard, 'ROOT', root), \
                 patch.object(app, 'ROOT', root):
                setup_wizard.apply_setup({
                    'facility_id': 'museum01',
                    'facility_name': 'テスト博物館',
                    'greeting': 'ようこそ！',
                    'persona': '丁寧に案内',
                    'city': '京都',
                    'nearest_station': '京都',
                    'demo_mode': False,
                    'gemini_model': 'gemini-3.5-flash-lite',
                    'enable_google_search': True,
                    'weather_enabled': True,
                    'transit_enabled': False,
                    'transit_plan': 'free',
                    'key_storage': 'dotenv',
                    'gemini_key': 'test-key-1234567890',
                    'mmd_enabled': True,
                    'mmd_model_path': 'assets/mmd/uka/MS_Uka.pmd',
                    'coeiroink_url': 'http://127.0.0.1:50032',
                    'speaker_uuid': 'uuid-123',
                    'style_id': 1,
                    'speed': 1.0,
                    'coeiroink_credit': 'COEIROINK:テスト話者',
                })

            fac = json.loads((root / 'facilities' / 'museum01' / 'facility.json').read_text(encoding='utf-8'))
            cfg = json.loads((root / 'config.json').read_text(encoding='utf-8'))
            env_text = (root / '.env').read_text(encoding='utf-8')
            fst_text = (root / 'guide.fst').read_text(encoding='utf-8')

            self.assertEqual(fac['name'], 'テスト博物館')
            self.assertEqual(fac['location']['city'], '京都')
            self.assertEqual(cfg['facility'], 'museum01')
            self.assertFalse(cfg['demo_mode'])
            self.assertEqual(cfg['mmd']['model_path'], 'assets/mmd/uka/MS_Uka.pmd')
            self.assertEqual(cfg['mmd']['idle_motion'], 'assets/mmd/uka/motion/stand.vmd')
            self.assertIn('CG-CA Uka', cfg['mmd']['credit'])
            self.assertIn('GEMINI_API_KEY=test-key-1234567890', env_text)
            self.assertIn('MODEL_ADD|guide|assets/mmd/uka/MS_Uka.pmd', fst_text)

    def test_save_facility_doc_and_reading_dictionary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'facilities' / 'sample' / 'docs').mkdir(parents=True)
            with patch.object(setup_wizard, 'ROOT', root):
                setup_wizard.save_facility_doc('test_01', 'info.md', '# テスト案内\n開館 9:00')
                docs = setup_wizard.list_facility_docs('test_01')
                self.assertEqual(docs, ['info.md'])

                setup_wizard.save_reading_entries('test_01', [('AI', 'エーアイ'), ('Wi-Fi', 'ワイファイ')])
                entries = setup_wizard.load_reading_entries('test_01')
                self.assertEqual(entries, [('AI', 'エーアイ'), ('Wi-Fi', 'ワイファイ')])

                with self.assertRaises(ValueError):
                    setup_wizard.save_facility_doc('test_01', '../bad.md', 'x')

    def test_fetch_gemini_models_parses_generate_content_models(self):
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({
                    'models': [
                        {'name': 'models/gemini-3.5-flash-lite', 'supportedGenerationMethods': ['generateContent']},
                        {'name': 'models/gemini-2.5-pro', 'supportedGenerationMethods': ['generateContent']},
                        {'name': 'models/embedding-001', 'supportedGenerationMethods': ['embedContent']},
                    ]
                }).encode('utf-8')

        with patch('urllib.request.urlopen', return_value=FakeResp()):
            models = setup_wizard.fetch_gemini_models('dummy-key-1234567890')
        self.assertEqual(models, ['gemini-3.5-flash-lite', 'gemini-2.5-pro'])


if __name__ == '__main__':
    unittest.main()
