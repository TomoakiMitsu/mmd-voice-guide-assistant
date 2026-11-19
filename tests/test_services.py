from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reading_dictionary import ReadingDictionaryError, apply_readings
from route_directions import parse_route
import services


class ServicesTests(unittest.TestCase):
    def test_reading_dictionary_longest_first_no_cascade(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / 'reading.csv'
            csv_path.write_text('表記,読み\nAI,エーアイ\nAI案内,エーアイアンナイ\nエーアイ,別読み\n', encoding='utf-8')
            out = apply_readings('aiとAI案内のテスト', csv_path)
        self.assertEqual(out, 'エーアイとエーアイアンナイのテスト')

    def test_reading_dictionary_rejects_invalid_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / 'reading.csv'
            csv_path.write_text('word,read\nA,エー\n', encoding='utf-8')
            with self.assertRaises(ReadingDictionaryError):
                apply_readings('A', csv_path)

    def test_parse_route_multiple_lines(self):
        data = {
            'ResultSet': {
                'Course': {
                    'Route': {
                        'transferCount': '1',
                        'Point': [
                            {'Station': {'Name': '東京', 'Type': 'train'}},
                            {'Station': {'Name': '名古屋', 'Type': 'train'}},
                            {'Station': {'Name': '栄', 'Type': 'train'}},
                        ],
                        'Line': [
                            {'Name': '東海道新幹線', 'Type': 'train', 'Destination': '新大阪'},
                            {'Name': '名古屋市営東山線', 'Type': 'train', 'Destination': '藤が丘'},
                        ],
                    },
                    'Price': [{'kind': 'FareSummary', 'Oneway': '11300'}],
                }
            }
        }
        parsed = parse_route(data)
        self.assertEqual(len(parsed['directions']), 2)
        self.assertEqual(parsed['fare_yen'], 11300)
        self.assertIn('東海道新幹線', parsed['directions'][0])
        self.assertIn('続いて、', parsed['directions'][1])

    def test_choose_mode_keywords(self):
        self.assertEqual(services.choose_mode('明日の天気は？', 'auto'), 'weather')
        self.assertEqual(services.choose_mode('東京駅までの乗り換え', 'auto'), 'transit')
        self.assertEqual(services.choose_mode('周辺のカフェを検索して', 'auto'), 'search')


if __name__ == '__main__':
    unittest.main()
