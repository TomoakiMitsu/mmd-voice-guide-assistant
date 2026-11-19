"""Fixed-endpoint external tools; no arbitrary URL fetching or credential logging."""
from datetime import datetime, timezone, timedelta
import json
import re
import urllib.request
import urllib.error
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from credentials import get_key
from route_directions import parse_route

JST = timezone(timedelta(hours=9))


def now_jst():
    return datetime.now(JST)


def get_json(url, parameters):
    try:
        with urllib.request.urlopen(url + '?' + urlencode(parameters), timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if '/search/course/extreme' in url and error.code in (401, 402, 403):
            raise ValueError('この駅すぱあとキーでは経路本文APIを利用できません。経路取得に対応したスタンダードまたはトライアルのキーを設定してください。') from None
        raise ValueError(f'外部サービスがHTTP {error.code}を返しました。APIの利用権限・利用枠を確認してください。') from None
    except (OSError, ValueError):
        # HTTP errors may contain a URL with the Ekispert key. Never expose them.
        raise ValueError('外部サービスに接続できません。APIキー・利用枠・接続を確認してください。') from None


def text_arg(value, name, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name}を指定してください')
    return value.strip()


def weather(args, facility):
    location = facility.get('location', {})
    city = args.get('location') or location.get('geocoding_name') or location.get('city')
    city = text_arg(city, '天気を調べる市町村')
    if city in (location.get('city'), facility.get('name'), 'ここ', '施設周辺'):
        city = location.get('geocoding_name') or location.get('city')
    day = args.get('date') or now_jst().date().isoformat()
    requested = datetime.strptime(day, '%Y-%m-%d').date()
    if not 0 <= (requested - now_jst().date()).days <= 6:
        raise ValueError('天気は今日から6日先までの予報に対応しています')
    language = 'en' if city.isascii() else 'ja'
    places = get_json('https://geocoding-api.open-meteo.com/v1/search', {
        'name': city, 'count': 5, 'language': language, 'format': 'json', 'countryCode': 'JP'}).get('results', [])
    if not places:
        raise ValueError('市町村が見つかりません。市名を確認してください')
    normalize = lambda name: re.sub(r'[市町村]$', '', name).casefold()
    exact = [p for p in places if normalize(p.get('name', '')) == normalize(city)]
    candidates = exact or places
    region = args.get('region')
    if region:
        region_name = re.sub(r'[都道府県]$', '', text_arg(region, '都道府県')).casefold()
        candidates = [p for p in candidates if re.sub(r'[都道府県]$', '', p.get('admin1', '')).casefold() == region_name]
    elif city in (location.get('geocoding_name'), location.get('city')) and location.get('geocoding_id'):
        configured = [p for p in candidates if p.get('id') == location['geocoding_id']]
        if configured:
            candidates = configured
    if not candidates:
        raise ValueError('指定された都道府県・市町村を確認してください')
    if len(candidates) > 1:
        return {'needs_clarification': True, 'candidates': [f"{p.get('admin1', '')} {p['name']}" for p in candidates],
                'message': '地域が複数あります。都道府県・市町村を確認してください。'}
    place = candidates[0]
    data = get_json('https://api.open-meteo.com/v1/forecast', {
        'latitude': place['latitude'], 'longitude': place['longitude'], 'timezone': 'Asia/Tokyo',
        'forecast_days': 7, 'current': 'temperature_2m,weather_code',
        'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max'})
    daily = data['daily']
    if day not in daily['time']:
        raise ValueError('指定日の予報がありません')
    index = daily['time'].index(day)
    return {'provider': 'Open-Meteo', 'location': place['name'], 'region': place.get('admin1'),
            'date': day, 'timezone': 'Asia/Tokyo', 'retrieved_at': now_jst().isoformat(),
            'forecast': {k: v[index] for k, v in daily.items()}, 'units': data.get('daily_units', {}),
            'current_model_estimate': data.get('current') if requested == now_jst().date() else None,
            'note': '数値モデルによる予報・推定値。観測実測値ではない。weather_codeはWMOコード。',
            'sources': [{'title': '天気予報: Open-Meteo（CC BY 4.0）', 'url': 'https://open-meteo.com/'}]}


class StationAmbiguity(ValueError):
    def __init__(self, name, candidates):
        super().__init__('同名駅があるため都道府県を確認してください')
        self.station_name = name
        self.candidates = candidates


def station(name, key, prefecture=None):
    name = text_arg(name, '駅名').removesuffix('駅')
    qualified = re.fullmatch(r'(.+?)[(（]([^()（）]+)[)）]', name)
    if qualified:
        name = qualified[1].removesuffix('駅')
        prefecture = prefecture or qualified[2]
    if ':' in name:
        raise ValueError('駅名は1つずつ指定してください')
    data = get_json('https://api.ekispert.jp/v1/json/station/light', {
        'key': key, 'name': name, 'type': 'train', 'nameMatchType': 'forward'})
    points = data.get('ResultSet', {}).get('Point', [])
    if isinstance(points, dict):
        points = [points]
    exact = [p for p in points if re.sub(r'[(（].*?[)）]$', '', p.get('Station', {}).get('Name', '')) == name]
    if prefecture:
        requested = re.sub(r'[都道府県]$', '', text_arg(prefecture, '都道府県'))
        exact = [p for p in exact if requested in (
            re.sub(r'[都道府県]$', '', p.get('Prefecture', {}).get('Name', '')),
            str(p.get('Prefecture', {}).get('code', '')),
            re.sub(r'[都道府県]$', '', re.search(r'[(（](.*?)[)）]', p['Station']['Name'])[1]) if re.search(r'[(（](.*?)[)）]', p['Station']['Name']) else '')]
    if len(exact) == 1:
        return str(exact[0]['Station']['code'])
    if len(exact) > 1:
        raise StationAmbiguity(name, [{'name': p['Station']['Name'], 'prefecture': p.get('Prefecture', {}).get('Name', '')} for p in exact])
    choices = [p.get('Station', {}).get('Name', '') for p in points]
    raise ValueError('駅を特定できません。駅名を確認してください。候補: ' + '、'.join(choices[:6]))


def transit(args, facility):
    key = get_key('ekispert')
    if not key:
        raise ValueError('駅すぱあとのAPIキーが未設定です。管理者の .env または画面の外部API設定で保存してください。')
    origin = text_arg(args.get('origin'), '出発駅')
    destination = text_arg(args.get('destination'), '到着駅')
    nearest = facility.get('location', {}).get('nearest_station')
    if origin in ('ここ', '施設', facility.get('name')) and nearest:
        origin = nearest
    if destination in ('ここ', '施設', facility.get('name')) and nearest:
        destination = nearest
    raw_time = args.get('datetime')
    when = datetime.fromisoformat(raw_time) if raw_time else now_jst()
    when = when.replace(tzinfo=JST) if when.tzinfo is None else when.astimezone(JST)
    search_type = args.get('search_type', 'departure')
    if search_type not in ('departure', 'arrival', 'firstTrain', 'lastTrain'):
        raise ValueError('探索種別が不正です')
    origin_code = station(origin, key, args.get('origin_prefecture'))
    destination_code = station(destination, key, args.get('destination_prefecture'))
    if facility.get('_transit_plan', 'free') == 'standard':
        data = get_json('https://api.ekispert.jp/v1/json/search/course/extreme', {
            'key': key, 'viaList': f'{origin_code}:{destination_code}',
            'date': when.strftime('%Y%m%d'), 'time': when.strftime('%H%M'),
            'searchType': search_type, 'answerCount': 1})
        return {'provider': '駅すぱあと 経路探索API', 'origin': origin, 'destination': destination,
                'requested_datetime': when.isoformat(), 'search_type': search_type,
                **parse_route(data),
                'sources': [{'title': '経路提供: 駅すぱあと', 'url': 'https://ekispert.com/'}]}
    data = get_json('https://api.ekispert.jp/v1/json/search/course/light', {
        'key': key, 'from': origin_code, 'to': destination_code, 'date': when.strftime('%Y%m%d'),
        'time': when.strftime('%H%M'), 'searchType': search_type, 'redirect': 'false'})
    uri = data.get('ResultSet', {}).get('ResourceURI', '')
    parsed = urlsplit(uri)
    if parsed.scheme != 'https' or parsed.hostname != 'roote.ekispert.net':
        raise ValueError('駅すぱあとから結果URLを取得できませんでした')
    uri = urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                     urlencode([(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in ('key', 'api_key')]), ''))
    result = {'provider': '駅すぱあとAPI フリープラン', 'origin': origin, 'destination': destination,
            'requested_datetime': when.isoformat(), 'search_type': search_type,
            'message': 'フリープランは結果ページURLの生成のみ。経路・運賃・時刻の本文は未取得。'
                       'directionsがない場合は、現在のキーではこの経路の音声案内ができないことを説明する。'
                       'リンクを見るように言うだけで完了にせず、経路取得対応キーの設定が必要と伝える。経路を推測しない。',
            'sources': [{'title': f'駅すぱあと: {origin} → {destination} の検索結果', 'url': uri}]}
    verified = next((r for r in facility.get('verified_routes', [])
                     if str(r.get('origin_code')) == origin_code and str(r.get('destination_code')) == destination_code), None)
    if verified:
        result['directions'] = verified['steps']
        result['route_basis'] = verified.get('note', '')
        result['checked_on'] = verified.get('checked_on')
        result['message'] = ('確認済みの基本経路のdirectionsを、路線・方向・乗換駅・降車駅を含めて直接説明する。'
                             'リンクを見るように言うだけで終わらせない。'
                             'この手順は公式資料で確認した経路であり、駅すぱあとの取得本文ではない。'
                             '発車時刻・運賃・最速かどうかは未確認で、推測しない。')
        result['sources'].extend(verified.get('sources', []))
    return result


DECLARATIONS = [
    {'name': 'get_weather', 'description': '日本の市町村の天気予報を取得。場所が不明なら質問する。場所省略時は施設周辺。日時は日本時間。',
     'parameters': {'type': 'OBJECT', 'properties': {'location': {'type': 'STRING', 'description': '市町村名のみ。施設周辺なら省略'}, 'region': {'type': 'STRING', 'description': '同名市町村を区別する都道府県。日本語の地名には日本語、英語には英語で指定'}, 'date': {'type': 'STRING', 'description': 'YYYY-MM-DD。省略時は今日'}}}},
    {'name': 'search_transit', 'description': '駅すぱあとで経路を検索する。directionsが返ったら路線・方向・乗換駅を直接説明し、リンク案内だけで終わらせない。経路本文を取得できないキーならその制約を説明する。出発駅・到着駅が揃うまで質問する。同名駅を確認した後の肯定の返事では履歴の出発駅・到着駅・確認済み都道府県を引き継いで再実行する。',
     'parameters': {'type': 'OBJECT', 'properties': {'origin': {'type': 'STRING'}, 'destination': {'type': 'STRING'},
        'origin_prefecture': {'type': 'STRING', 'description': '出発駅の都道府県。確認された場合に指定'},
        'destination_prefecture': {'type': 'STRING', 'description': '到着駅の都道府県。確認された場合に指定'},
        'datetime': {'type': 'STRING', 'description': '日本時間のISO8601日時。指定なしは現在'},
        'search_type': {'type': 'STRING', 'enum': ['departure', 'arrival', 'firstTrain', 'lastTrain']}}, 'required': ['origin', 'destination']}},
    {'name': 'search_web', 'description': 'Google検索で公開情報を確認する。施設資料に答えがない、情報が古い、店・イベント・営業時間・料金など変化する情報は積極的に利用する。検索語に内部の運用情報や秘密情報を含めない。',
     'parameters': {'type': 'OBJECT', 'properties': {'query': {'type': 'STRING', 'description': '公開情報の検索語'}}, 'required': ['query']}}
]


def choose_mode(question, mode, history=None):
    if mode not in ('auto', 'local', 'search', 'weather', 'transit'):
        raise ValueError('案内モードが不正です')
    if mode != 'auto':
        return mode
    if re.search(r'天気|天候|気温|降水|雨|晴れ|傘', question):
        return 'weather'
    if re.search(r'乗[り]?換[え]?|電車|終電|始発|駅から|駅への|までの行き方|運賃|発車|到着時刻', question):
        return 'transit'
    if re.search(r'^(?:それ|そこ|その|他には|ほかには|帰り|明日|明後日|週末|はい|そう|あってる|合ってる|うん)', question):
        past = (history or [])[-6:]
        for index in range(len(past)-1, -1, -1):
            item = past[index]
            if item.get('role') == 'user':
                previous = choose_mode(item.get('text', ''), 'auto', past[:index])
                if previous in ('weather', 'transit', 'search'):
                    return previous
    if re.search(r'検索|調べ|最新|ニュース|イベント|開催|おすすめ|営業時間|開館|休館|定休|料金|予約|混雑|空[き席]|周辺|近くの|飲食店|ランチ|カフェ|レストラン|今週|今日|明日', question):
        return 'search'
    return 'auto'


def execute(name, args, facility):
    try:
        if not isinstance(args, dict):
            raise ValueError('検索条件を確認してください')
        if name == 'get_weather':
            return weather(args, facility)
        if name == 'search_transit':
            return transit(args, facility)
        raise ValueError('未対応の検索です')
    except StationAmbiguity as error:
        return {'needs_clarification': True, 'station': error.station_name, 'candidates': error.candidates,
                'instruction': '都道府県を確認する。ユーザーが候補を肯定したら、元の出発・到着駅とその都道府県を付けて再検索する。'}
    except (OSError, ValueError, KeyError, TypeError):
        # Explicit user-action messages are safe; never stringify network exceptions.
        import sys
        error = sys.exc_info()[1]
        return {'error': str(error) if isinstance(error, ValueError) else '外部情報を取得できませんでした。',
                'instruction': '結果を取得できていない。天気・経路・時刻を推測せず、原因と必要な操作を案内する。'}
