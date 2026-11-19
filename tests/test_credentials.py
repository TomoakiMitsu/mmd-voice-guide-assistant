import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import credentials


class CredentialsTests(unittest.TestCase):
    def test_load_dotenv_parses_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            env_file.write_text('# comment\nGEMINI_API_KEY="abc123456789012345"\nEKISPERT_API_KEY=\'xyz\'\n', encoding='utf-8')
            parsed = credentials.load_dotenv(env_file)
        self.assertEqual(parsed['GEMINI_API_KEY'], 'abc123456789012345')
        self.assertEqual(parsed['EKISPERT_API_KEY'], 'xyz')

    def test_save_key_rejects_invalid(self):
        with self.assertRaises(ValueError):
            credentials.save_key('short')
        with self.assertRaises(ValueError):
            credentials.save_key('a' * 20 + ' space')

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI only')
    def test_dpapi_roundtrip(self):
        encrypted = credentials.crypt(b'test-secret-key-12345')
        self.assertEqual(credentials.crypt(encrypted, decrypt=True), b'test-secret-key-12345')


if __name__ == '__main__':
    unittest.main()
