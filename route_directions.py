"""Convert actual Ekispert route data into ordered, speakable instructions."""
from datetime import datetime


def array(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def plain(value):
    return str(value.get('text', '')) if isinstance(value, dict) else str(value or '')


def point_name(point):
    station = point.get('Station', {})
    name = station.get('Name') or point.get('Name')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('取得した経路に駅・地点名が不足しています。再検索してください。')
    kind = plain(station.get('Type'))
    return name + ('駅' if kind == 'train' and not name.endswith('駅') else '')


def time_value(state):
    value = plain((state or {}).get('Datetime'))
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return None


def parse_route(data):
    courses = array(data.get('ResultSet', {}).get('Course'))
    if not courses:
        raise ValueError('指定した条件で経路が見つかりませんでした。駅名や日時を確認してください。')
    course = courses[0]
    route = course.get('Route', {})
    points, lines = array(route.get('Point')), array(route.get('Line'))
    if len(points) != len(lines) + 1 or not lines:
        raise ValueError('経路の順序を確認できませんでした。再検索してください。')
    steps, segments = [], []
    for index, line in enumerate(lines):
        start, end = point_name(points[index]), point_name(points[index+1])
        name = line.get('Name')
        if not isinstance(name, str) or not name:
            raise ValueError('取得した経路に路線名がありません。再検索してください。')
        kind = plain(line.get('Type'))
        direction = plain(line.get('Destination'))
        if kind == 'walk' or name == '徒歩':
            sentence = f'{start}から{end}まで徒歩で移動します。'
        else:
            bound = f'（{direction}方面）' if direction and direction not in name else ''
            sentence = f'{start}から{name}{bound}に乗り、{end}で降ります。'
            if index > 0:
                sentence = '続いて、' + sentence
        steps.append(sentence)
        segments.append({'from': start, 'to': end, 'line': name, 'direction': direction,
                         'departure': time_value(line.get('DepartureState')),
                         'arrival': time_value(line.get('ArrivalState')),
                         'time_basis': line.get('TimeReliability')})
    prices = {p.get('kind'): p.get('Oneway') for p in array(course.get('Price'))
              if p.get('kind') in ('FareSummary', 'ChargeSummary')}
    fare = sum(int(value) for value in prices.values()) if 'FareSummary' in prices and all(str(v).isdigit() for v in prices.values()) else None
    return {'directions': steps, 'segments': segments, 'transfer_count': route.get('transferCount'),
            'fare_yen': fare, 'data_type': course.get('dataType'),
            'message': 'directionsの乗車路線・乗換駅・降車駅を順番に直接読み上げる。リンク案内だけで終わらせない。'
                       '指定条件で返された先頭の経路。リアルタイムの遅延・運休を確認したとは言わない。'
                       '時刻や運賃は取得値のみ利用する。値がない場合は推測しない。'}
