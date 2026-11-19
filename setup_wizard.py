"""GUI setup & management tool for facility settings, docs, reading dictionary, APIs, MMD, and COEIROINK."""
import csv
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import urllib.error
import urllib.request

import app
import credentials
import launcher
from reading_dictionary import ReadingDictionaryError, apply_readings

ROOT = Path(__file__).resolve().parent


def fetch_gemini_models(api_key):
    """Fetch available generateContent-capable Gemini models via Gemini API."""
    if not api_key or not api_key.strip():
        raise ValueError('Gemini APIキーが未設定です。APIキーを入力または保存してから取得してください。')
    req = urllib.request.Request(
        'https://generativelanguage.googleapis.com/v1beta/models',
        headers={'x-goog-api-key': api_key.strip()},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'Gemini APIからモデル一覧を取得できませんでした（HTTP {exc.code}）。APIキーを確認してください。') from None
    except (OSError, ValueError):
        raise ValueError('Gemini APIに接続できません。ネットワーク設定を確認してください。') from None
    models = []
    for item in data.get('models', []):
        methods = item.get('supportedGenerationMethods', [])
        name = item.get('name', '')
        if 'generateContent' in methods and name.startswith('models/'):
            model_id = name.removeprefix('models/')
            if 'gemini' in model_id.lower():
                models.append(model_id)
    return sorted(set(models), reverse=True)


def ensure_facility_dir(facility_id):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', facility_id):
        raise ValueError('施設IDは英数字・ハイフン・アンダースコアのみで指定してください。')
    facility_dir = ROOT / 'facilities' / facility_id
    sample_dir = ROOT / 'facilities' / 'sample'
    if not facility_dir.exists():
        if sample_dir.is_dir():
            shutil.copytree(sample_dir, facility_dir)
        else:
            (facility_dir / 'docs').mkdir(parents=True, exist_ok=True)
    else:
        (facility_dir / 'docs').mkdir(parents=True, exist_ok=True)
    return facility_dir


def list_facility_docs(facility_id):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', facility_id):
        return []
    docs_dir = ROOT / 'facilities' / facility_id / 'docs'
    if not docs_dir.is_dir():
        return []
    files = []
    for path in sorted(docs_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in ('.md', '.txt', '.json') and not path.is_symlink():
            files.append(path.name)
    return files


def save_facility_doc(facility_id, filename, content):
    facility_dir = ensure_facility_dir(facility_id)
    docs_dir = (facility_dir / 'docs').resolve()
    name = Path(filename.strip()).name
    if not name or name != filename.strip() or Path(name).suffix.lower() not in ('.md', '.txt', '.json'):
        raise ValueError('ファイル名は拡張子 .md / .txt / .json のいずれかで指定してください。')
    target = (docs_dir / name).resolve()
    if not target.is_relative_to(docs_dir):
        raise ValueError('不正なファイルパスです。')
    encoded = content.encode('utf-8')
    if len(encoded) > 150000:
        raise ValueError('1ファイルのサイズは150KB以内にしてください。')
    target.write_bytes(encoded)
    return target


def load_reading_entries(facility_id):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', facility_id):
        return []
    csv_path = ROOT / 'facilities' / facility_id / 'reading_dictionary.csv'
    if not csv_path.is_file():
        return []
    entries = []
    with csv_path.open(encoding='utf-8-sig', newline='') as f:
        rows = csv.DictReader(f)
        if rows.fieldnames != ['表記', '読み']:
            return []
        for row in rows:
            s = (row.get('表記') or '').strip()
            r = (row.get('読み') or '').strip()
            if s and r:
                entries.append((s, r))
    return entries


def save_reading_entries(facility_id, entries):
    facility_dir = ensure_facility_dir(facility_id)
    csv_path = facility_dir / 'reading_dictionary.csv'
    tmp_path = facility_dir / 'reading_dictionary.tmp'
    with tmp_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['表記', '読み'])
        for surface, reading in entries:
            writer.writerow([surface.strip(), reading.strip()])
    try:
        # Validate using the production parser before replacing.
        apply_readings('テスト', tmp_path)
    except ReadingDictionaryError:
        tmp_path.unlink(missing_ok=True)
        raise
    tmp_path.replace(csv_path)
    return csv_path


def apply_setup(data):
    """Validate and persist wizard settings to config, facility, keys, and launcher."""
    facility_id = (data.get('facility_id') or '').strip()
    facility_dir = ensure_facility_dir(facility_id)

    facility_file = facility_dir / 'facility.json'
    if facility_file.is_file():
        facility = app.read_json(facility_file)
    else:
        facility = {'knowledge': [], 'notes': ''}

    name = (data.get('facility_name') or '').strip()
    if not name:
        raise ValueError('施設名を入力してください。')
    facility['name'] = name
    facility['greeting'] = (data.get('greeting') or '').strip() or 'こんにちは。ご案内いたします。'
    facility['persona'] = (data.get('persona') or '').strip() or '親しみやすく丁寧な日本語で案内してください。'
    city = (data.get('city') or '').strip()
    facility['location'] = {
        'city': city,
        'geocoding_name': city,
        'nearest_station': (data.get('nearest_station') or '').strip(),
    }
    facility_file.write_text(json.dumps(facility, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    config_path = ROOT / 'config.json'
    if not config_path.exists():
        config_path.write_bytes((ROOT / 'config.example.json').read_bytes())
    config = app.read_json(config_path)

    config['facility'] = facility_id
    config['demo_mode'] = bool(data.get('demo_mode', True))

    gemini_cfg = config.setdefault('gemini', {})
    model_name = (data.get('gemini_model') or 'gemini-3.5-flash-lite').strip()
    if not re.fullmatch(r'[a-zA-Z0-9._-]+', model_name):
        raise ValueError('Geminiモデル名が不正です。')
    gemini_cfg['model'] = model_name
    try:
        max_tokens = int(data.get('max_output_tokens', gemini_cfg.get('max_output_tokens', 512)))
        if not 64 <= max_tokens <= 8192:
            raise ValueError
        gemini_cfg['max_output_tokens'] = max_tokens
    except (TypeError, ValueError) as exc:
        raise ValueError('最大出力トークン数は 64〜8192 の整数で指定してください。') from exc
    gemini_cfg['enable_google_search'] = bool(data.get('enable_google_search', True))

    ext_cfg = config.setdefault('external_apis', {})
    ext_cfg['weather_enabled'] = bool(data.get('weather_enabled', True))
    ext_cfg['transit_enabled'] = bool(data.get('transit_enabled', True))
    transit_plan = data.get('transit_plan', 'free')
    if transit_plan not in ('free', 'standard'):
        raise ValueError('駅すぱあとプランの指定が不正です。')
    ext_cfg['transit_plan'] = transit_plan

    mmd_cfg = config.setdefault('mmd', {})
    mmd_cfg['enabled'] = bool(data.get('mmd_enabled', False))
    win_size = (data.get('mmd_window_size') or mmd_cfg.get('window_size', '900,720')).strip()
    if not re.fullmatch(r'[0-9]+,[0-9]+', win_size):
        raise ValueError('MMDウィンドウサイズは「幅,高さ」（例: 900,720）で指定してください。')
    mmd_cfg['window_size'] = win_size
    model_rel = app.safe_relpath(data.get('mmd_model_path', mmd_cfg.get('model_path', 'assets/mmd/gene/Gene.pmd')))
    if model_rel:
        mmd_cfg['model_path'] = model_rel
        model_dir = (ROOT / model_rel).parent
        idle = model_dir / 'motion' / 'stand.vmd'
        thinking = model_dir / 'motion' / '16_thinking.vmd'
        mmd_cfg['idle_motion'] = idle.relative_to(ROOT).as_posix() if idle.is_file() else ''
        mmd_cfg['thinking_motion'] = thinking.relative_to(ROOT).as_posix() if thinking.is_file() else ''
        if model_rel.startswith('assets/mmd/uka/'):
            mmd_cfg['credit'] = 'CG-CA Uka (c) 2023-2024 by Nagoya Institute of Technology, Moonshot R&D Goal 1 Avatar Symbiotic Society (CC BY 4.0)'
        elif model_rel.startswith('assets/mmd/gene/'):
            mmd_cfg['credit'] = 'CG-CA Gene (c) 2023 by Nagoya Institute of Technology, Moonshot R&D Goal 1 Avatar Symbiotic Society (CC BY 4.0)'

    coeiro_cfg = config.setdefault('coeiroink', {})
    coeiro_cfg['url'] = app.safe_http_url(data.get('coeiroink_url') or 'http://127.0.0.1:50032', 'COEIROINK URL')
    coeiro_cfg['speaker_uuid'] = (data.get('speaker_uuid') or coeiro_cfg.get('speaker_uuid', '')).strip()
    try:
        coeiro_cfg['style_id'] = int(data.get('style_id', coeiro_cfg.get('style_id', 0)))
        coeiro_cfg['speed'] = float(data.get('speed', coeiro_cfg.get('speed', 1.1)))
    except (TypeError, ValueError) as exc:
        raise ValueError('COEIROINKのスタイルIDまたは話速の数値が不正です。') from exc
    if data.get('coeiroink_credit'):
        coeiro_cfg['credit'] = data['coeiroink_credit'].strip()

    log_cfg = config.setdefault('logging', {})
    log_cfg['save_conversation'] = bool(data.get('save_conversation', True))

    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    app.sync_mmd_files(config)

    key_storage = data.get('key_storage', 'dpapi')
    gemini_key = (data.get('gemini_key') or '').strip()
    ekispert_key = (data.get('ekispert_key') or '').strip()
    if key_storage == 'dotenv':
        env_values = credentials.load_dotenv()
        if gemini_key:
            env_values['GEMINI_API_KEY'] = credentials.validate_key(gemini_key)
        if ekispert_key:
            env_values['EKISPERT_API_KEY'] = credentials.validate_key(ekispert_key)
        lines = [f'{k}={v}' for k, v in env_values.items()]
        (ROOT / '.env').write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
    else:
        if gemini_key:
            credentials.save_key(gemini_key, 'gemini')
        if ekispert_key:
            credentials.save_key(ekispert_key, 'ekispert')

    local_paths = launcher.load_paths()
    for kind in ('coeiroink', 'mmd'):
        val = (data.get(f'{kind}_exe') or '').strip()
        if val:
            local_paths[kind] = val
    if local_paths:
        (ROOT / 'launcher.local.json').write_text(
            json.dumps(local_paths, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
        )

    return config, facility


class SetupWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('観光案内アシスタント 設定・管理ツール')
        self.geometry('780x700')
        self.minsize(720, 640)

        try:
            self.cfg, self.fac = app.settings()
        except Exception:
            if not (ROOT / 'config.json').exists():
                (ROOT / 'config.json').write_bytes((ROOT / 'config.example.json').read_bytes())
            self.cfg = app.read_json(ROOT / 'config.json')
            self.fac = {'name': 'サンプル観光案内所', 'greeting': '', 'persona': '', 'location': {}}
        self.local_paths = launcher.load_paths()
        self.speaker_choices = []

        self._build_vars()
        self._build_ui()
        self._refresh_facility_related_views()

    def _build_vars(self):
        loc = self.fac.get('location', {})
        gemini_cfg = self.cfg.get('gemini', {})
        ext_cfg = self.cfg.get('external_apis', {})
        mmd_cfg = self.cfg.get('mmd', {})
        coeiro_cfg = self.cfg.get('coeiroink', {})

        self.var_existing_facility = tk.StringVar(value=self.cfg.get('facility', 'sample'))
        self.var_facility_id = tk.StringVar(value=self.cfg.get('facility', 'sample'))
        self.var_facility_name = tk.StringVar(value=self.fac.get('name', ''))
        self.var_greeting = tk.StringVar(value=self.fac.get('greeting', ''))
        self.var_persona = tk.StringVar(value=self.fac.get('persona', ''))
        self.var_city = tk.StringVar(value=loc.get('city', ''))
        self.var_station = tk.StringVar(value=loc.get('nearest_station', ''))

        self.var_demo_mode = tk.BooleanVar(value=bool(self.cfg.get('demo_mode', True)))
        self.var_gemini_model = tk.StringVar(value=gemini_cfg.get('model', 'gemini-3.5-flash-lite'))
        self.var_max_tokens = tk.StringVar(value=str(gemini_cfg.get('max_output_tokens', 512)))
        self.var_google_search = tk.BooleanVar(value=bool(gemini_cfg.get('enable_google_search', True)))
        self.var_weather = tk.BooleanVar(value=bool(ext_cfg.get('weather_enabled', True)))
        self.var_transit = tk.BooleanVar(value=bool(ext_cfg.get('transit_enabled', True)))
        self.var_transit_plan = tk.StringVar(value=ext_cfg.get('transit_plan', 'free'))
        self.var_key_storage = tk.StringVar(value='dpapi' if os.name == 'nt' else 'dotenv')
        self.var_gemini_key = tk.StringVar(value='')
        self.var_ekispert_key = tk.StringVar(value='')
        self.var_save_conversation = tk.BooleanVar(value=bool(self.cfg.get('logging', {}).get('save_conversation', True)))

        self.var_mmd_enabled = tk.BooleanVar(value=bool(mmd_cfg.get('enabled', False)))
        self.var_mmd_model = tk.StringVar(value=mmd_cfg.get('model_path', 'assets/mmd/gene/Gene.pmd'))
        self.var_mmd_window_size = tk.StringVar(value=str(mmd_cfg.get('window_size', '900,720')))
        self.var_coeiro_url = tk.StringVar(value=coeiro_cfg.get('url', 'http://127.0.0.1:50032'))
        self.var_speaker_uuid = tk.StringVar(value=coeiro_cfg.get('speaker_uuid', ''))
        self.var_style_id = tk.StringVar(value=str(coeiro_cfg.get('style_id', 0)))
        self.var_speed = tk.StringVar(value=str(coeiro_cfg.get('speed', 1.1)))
        self.var_coeiro_credit = tk.StringVar(value=coeiro_cfg.get('credit', 'COEIROINK:つくよみちゃん'))
        self.var_coeiro_exe = tk.StringVar(value=self.local_paths.get('coeiroink', ''))
        self.var_mmd_exe = tk.StringVar(value=self.local_paths.get('mmd', ''))

        self.var_doc_filename = tk.StringVar(value='guide.md')
        self.var_dict_surface = tk.StringVar(value='')
        self.var_dict_reading = tk.StringVar(value='')
        self.var_dict_test_in = tk.StringVar(value='AIとWi-Fiの案内です。')
        self.var_dict_test_out = tk.StringVar(value='')

    def _build_ui(self):
        header = ttk.Frame(self, padding=(16, 12, 16, 6))
        header.pack(fill='x')
        ttk.Label(header, text='観光案内アシスタント 設定・管理ツール', font=('Yu Gothic UI', 13, 'bold')).pack(anchor='w')
        ttk.Label(header, text='初期設定だけでなく、導入後の施設変更・施設資料の編集・読み辞書の更新にも使えます。').pack(anchor='w')

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=16, pady=8)

        self._tab_facility()
        self._tab_docs()
        self._tab_dictionary()
        self._tab_apis()
        self._tab_character_voice()

        footer = ttk.Frame(self, padding=(16, 6, 16, 14))
        footer.pack(fill='x')
        ttk.Button(footer, text='戻る', command=self._prev_tab).pack(side='left')
        ttk.Button(footer, text='次へ', command=self._next_tab).pack(side='left', padx=8)
        ttk.Button(footer, text='全体設定を保存', command=self._save).pack(side='right')
        ttk.Button(footer, text='閉じる', command=self.destroy).pack(side='right', padx=8)

    def _hint(self, parent, text, row, col=1, columnspan=1):
        ttk.Label(parent, text=text, foreground='#5a6b63', font=('Yu Gothic UI', 8)).grid(
            row=row, column=col, columnspan=columnspan, sticky='w', pady=(0, 6)
        )

    def _fill_facility_example(self):
        self.var_facility_id.set('test_01')
        self.var_facility_name.set('サンプル科学館 観光案内所')
        self.var_greeting.set('こんにちは。サンプル科学館の案内アシスタントです。館内や周辺についてお気軽にご質問ください。')
        self.var_persona.set('親しみやすく丁寧な日本語で、原則3文以内で分かりやすく案内してください。')
        self.var_city.set('京都市')
        self.var_station.set('京都')

    def _on_select_existing_facility(self, _event=None):
        fid = self.var_existing_facility.get().strip()
        if not fid:
            return
        fac_file = ROOT / 'facilities' / fid / 'facility.json'
        if fac_file.is_file():
            fac = app.read_json(fac_file)
            loc = fac.get('location', {})
            self.var_facility_id.set(fid)
            self.var_facility_name.set(fac.get('name', ''))
            self.var_greeting.set(fac.get('greeting', ''))
            self.var_persona.set(fac.get('persona', ''))
            self.var_city.set(loc.get('city', ''))
            self.var_station.set(loc.get('nearest_station', ''))
            self._refresh_facility_related_views()

    def _refresh_facility_choices(self):
        ids = [item['id'] for item in app.list_facilities()]
        if hasattr(self, 'facility_combo'):
            self.facility_combo['values'] = ids

    def _refresh_facility_related_views(self):
        fid = self.var_facility_id.get().strip()
        self._refresh_facility_choices()
        if hasattr(self, 'docs_list'):
            self.docs_list.delete(0, tk.END)
            for name in list_facility_docs(fid):
                self.docs_list.insert(tk.END, name)
            self.var_doc_filename.set('guide.md')
            docs = list_facility_docs(fid)
            if docs:
                self._load_doc_content(docs[0])
            else:
                self.doc_editor.delete('1.0', tk.END)
        if hasattr(self, 'dict_tree'):
            for item in self.dict_tree.get_children():
                self.dict_tree.delete(item)
            for surface, reading in load_reading_entries(fid):
                self.dict_tree.insert('', tk.END, values=(surface, reading))

    def _tab_facility(self):
        frame = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(frame, text='1. 施設基本設定')
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text='既存施設を読み込む').grid(row=0, column=0, sticky='w', pady=4, padx=(0, 10))
        self.facility_combo = ttk.Combobox(frame, textvariable=self.var_existing_facility, state='readonly')
        self.facility_combo.grid(row=0, column=1, sticky='ew', pady=4)
        self.facility_combo.bind('<<ComboboxSelected>>', self._on_select_existing_facility)
        self._hint(frame, '登録済みの施設を切り替えて編集したい場合に選択します', 1)

        rows = [
            ('施設ID（半角英数字・_-）', self.var_facility_id, '例: test_01, museum_01（新規IDならsampleを元に自動作成）'),
            ('施設名', self.var_facility_name, '例: ○○市観光案内所 / △△科学館'),
            ('最初の挨拶', self.var_greeting, '例: こんにちは。施設や周辺についてお気軽にご質問ください。'),
            ('口調・キャラクター設定', self.var_persona, '例: 親しみやすく丁寧な日本語で、原則3文以内で案内してください。'),
            ('所在地（市町村・任意）', self.var_city, '例: 京都市 / 札幌市（空欄なら天気を聞く際に場所を確認します）'),
            ('最寄り駅（任意）', self.var_station, '例: 京都 / 札幌（空欄なら乗換検索時に出発駅を確認します）'),
        ]
        r = 2
        for label, var, hint in rows:
            ttk.Label(frame, text=label).grid(row=r, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
            ttk.Entry(frame, textvariable=var).grid(row=r, column=1, sticky='ew', pady=(4, 0))
            self._hint(frame, hint, r + 1)
            r += 2

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=r, column=0, columnspan=2, sticky='w', pady=8)
        ttk.Button(btn_row, text='入力例をフォームに入れる', command=self._fill_facility_example).pack(side='left')
        ttk.Button(btn_row, text='この施設IDの資料・辞書を読み直す', command=self._refresh_facility_related_views).pack(side='left', padx=10)

    def _tab_docs(self):
        frame = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(frame, text='2. 施設資料 (docs)')
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(2, weight=1)

        top = ttk.Frame(frame)
        top.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        ttk.Label(top, text='対象施設の docs/ フォルダ内の資料（.md / .txt / .json、1ファイル150KB以内・合計4万文字以内）').pack(side='left')

        left = ttk.Frame(frame)
        left.grid(row=1, column=0, rowspan=2, sticky='ns', padx=(0, 12))
        ttk.Label(left, text='資料ファイル一覧').pack(anchor='w')
        self.docs_list = tk.Listbox(left, width=24, height=16)
        self.docs_list.pack(fill='y', expand=True, pady=4)
        self.docs_list.bind('<<ListboxSelect>>', self._on_doc_selected)
        ttk.Button(left, text='PCからファイル追加', command=self._import_doc_file).pack(fill='x', pady=2)
        ttk.Button(left, text='docsフォルダを開く', command=self._open_docs_folder).pack(fill='x', pady=2)

        right_top = ttk.Frame(frame)
        right_top.grid(row=1, column=1, sticky='ew')
        ttk.Label(right_top, text='ファイル名:').pack(side='left')
        ttk.Entry(right_top, textvariable=self.var_doc_filename, width=28).pack(side='left', padx=6)
        ttk.Button(right_top, text='入力例を入れる', command=self._fill_doc_example).pack(side='left', padx=4)
        ttk.Button(right_top, text='この資料を保存', command=self._save_current_doc).pack(side='right')

        self.doc_editor = scrolledtext.ScrolledText(frame, wrap='word', font=('Yu Gothic UI', 10))
        self.doc_editor.grid(row=2, column=1, sticky='nsew', pady=(6, 0))

    def _on_doc_selected(self, _event=None):
        sel = self.docs_list.curselection()
        if not sel:
            return
        self._load_doc_content(self.docs_list.get(sel[0]))

    def _load_doc_content(self, filename):
        fid = self.var_facility_id.get().strip()
        path = ROOT / 'facilities' / fid / 'docs' / filename
        self.var_doc_filename.set(filename)
        self.doc_editor.delete('1.0', tk.END)
        if path.is_file():
            self.doc_editor.insert('1.0', path.read_text(encoding='utf-8-sig'))

    def _fill_doc_example(self):
        self.var_doc_filename.set('guide.md')
        self.doc_editor.delete('1.0', tk.END)
        self.doc_editor.insert('1.0', (
            '# 施設案内（入力例）\n\n'
            '## 開館時間・休館日\n'
            '- 開館時間: 9:30〜17:00（最終入館 16:30）\n'
            '- 休館日: 毎週月曜日（祝日の場合は翌平日）\n\n'
            '## 料金\n'
            '- 大人: 500円 / 高校・大学生: 300円 / 中学生以下: 無料\n\n'
            '## アクセス・設備\n'
            '- 最寄り駅から徒歩5分\n'
            '- バリアフリートイレ、授乳室、無料Wi-Fiあり\n'
        ))

    def _import_doc_file(self):
        fid = self.var_facility_id.get().strip()
        if fid == 'sample':
            messagebox.showwarning('確認', 'sampleは公開用テンプレートです。施設設定タブで別の施設IDに変更してから追加してください。', parent=self)
            return
        selected = filedialog.askopenfilename(
            parent=self,
            title='追加する施設資料を選択',
            filetypes=[('資料ファイル', '*.md *.txt *.json')],
        )
        if not selected:
            return
        src = Path(selected)
        try:
            content = src.read_text(encoding='utf-8-sig')
            save_facility_doc(fid, src.name, content)
            self._refresh_facility_related_views()
            self._load_doc_content(src.name)
            messagebox.showinfo('追加完了', f'{src.name} を保存しました。', parent=self)
        except Exception as exc:
            messagebox.showerror('エラー', str(exc), parent=self)

    def _save_current_doc(self):
        fid = self.var_facility_id.get().strip()
        if fid == 'sample':
            if not messagebox.askyesno('公開用テンプレートの確認', '施設IDが「sample」です。公開用テンプレートを上書きしますか？', parent=self):
                return
        try:
            content = self.doc_editor.get('1.0', 'end-1c')
            target = save_facility_doc(fid, self.var_doc_filename.get(), content)
            self._refresh_facility_related_views()
            self.var_doc_filename.set(target.name)
            messagebox.showinfo('保存完了', f'施設資料 {target.name} を保存しました。次の質問から反映されます。', parent=self)
        except Exception as exc:
            messagebox.showerror('保存エラー', str(exc), parent=self)

    def _tab_dictionary(self):
        frame = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(frame, text='3. 読み辞書')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, text='COEIROINKで正しく読ませたい固有名詞・英字の読み方を登録します（画面の表示文は変わりません）。').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 8)
        )

        self.dict_tree = ttk.Treeview(frame, columns=('surface', 'reading'), show='headings', height=10)
        self.dict_tree.heading('surface', text='表記（例: AI, Wi-Fi, ○○館）')
        self.dict_tree.heading('reading', text='読み（例: エーアイ, ワイファイ）')
        self.dict_tree.column('surface', width=260)
        self.dict_tree.column('reading', width=360)
        self.dict_tree.grid(row=1, column=0, columnspan=2, sticky='nsew', pady=(0, 8))
        self.dict_tree.bind('<<TreeviewSelect>>', self._on_dict_selected)

        edit_row = ttk.Frame(frame)
        edit_row.grid(row=2, column=0, columnspan=2, sticky='ew', pady=4)
        ttk.Label(edit_row, text='表記:').pack(side='left')
        ttk.Entry(edit_row, textvariable=self.var_dict_surface, width=22).pack(side='left', padx=(4, 12))
        ttk.Label(edit_row, text='読み:').pack(side='left')
        ttk.Entry(edit_row, textvariable=self.var_dict_reading, width=28).pack(side='left', padx=(4, 12))
        ttk.Button(edit_row, text='追加 / 更新', command=self._add_dict_entry).pack(side='left', padx=2)
        ttk.Button(edit_row, text='選択削除', command=self._delete_dict_entry).pack(side='left', padx=2)

        action_row = ttk.Frame(frame)
        action_row.grid(row=3, column=0, columnspan=2, sticky='ew', pady=6)
        ttk.Button(action_row, text='入力例を追加', command=self._fill_dict_example).pack(side='left')
        ttk.Button(action_row, text='読み辞書を保存', command=self._save_dictionary).pack(side='right')

        test_box = ttk.LabelFrame(frame, text='読み変換テスト（保存後に確認できます）', padding=8)
        test_box.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        test_box.columnconfigure(1, weight=1)
        ttk.Label(test_box, text='元の文:').grid(row=0, column=0, sticky='w', padx=(0, 6))
        ttk.Entry(test_box, textvariable=self.var_dict_test_in).grid(row=0, column=1, sticky='ew')
        ttk.Button(test_box, text='変換テスト', command=self._test_dictionary).grid(row=0, column=2, padx=(6, 0))
        ttk.Label(test_box, text='読み上げ文:').grid(row=1, column=0, sticky='w', padx=(0, 6), pady=(6, 0))
        ttk.Label(test_box, textvariable=self.var_dict_test_out, foreground='#245a48').grid(
            row=1, column=1, columnspan=2, sticky='w', pady=(6, 0)
        )

    def _on_dict_selected(self, _event=None):
        sel = self.dict_tree.selection()
        if not sel:
            return
        vals = self.dict_tree.item(sel[0], 'values')
        if len(vals) == 2:
            self.var_dict_surface.set(vals[0])
            self.var_dict_reading.set(vals[1])

    def _add_dict_entry(self):
        s = self.var_dict_surface.get().strip()
        r = self.var_dict_reading.get().strip()
        if not s or not r:
            messagebox.showwarning('確認', '表記と読みの両方を入力してください。', parent=self)
            return
        for item in self.dict_tree.get_children():
            vals = self.dict_tree.item(item, 'values')
            if vals and vals[0].casefold() == s.casefold():
                self.dict_tree.item(item, values=(s, r))
                return
        self.dict_tree.insert('', tk.END, values=(s, r))

    def _delete_dict_entry(self):
        for item in self.dict_tree.selection():
            self.dict_tree.delete(item)

    def _fill_dict_example(self):
        examples = [('AI', 'エーアイ'), ('Wi-Fi', 'ワイファイ'), ('QRコード', 'キューアールコード')]
        existing = {self.dict_tree.item(i, 'values')[0].casefold() for i in self.dict_tree.get_children()}
        for s, r in examples:
            if s.casefold() not in existing:
                self.dict_tree.insert('', tk.END, values=(s, r))

    def _save_dictionary(self):
        fid = self.var_facility_id.get().strip()
        if fid == 'sample':
            if not messagebox.askyesno('公開用テンプレートの確認', '施設IDが「sample」です。公開用テンプレートを上書きしますか？', parent=self):
                return
        entries = [self.dict_tree.item(i, 'values') for i in self.dict_tree.get_children()]
        try:
            save_reading_entries(fid, entries)
            messagebox.showinfo('保存完了', '読み辞書を保存しました。次の音声合成から反映されます。', parent=self)
        except Exception as exc:
            messagebox.showerror('保存エラー', str(exc), parent=self)

    def _test_dictionary(self):
        fid = self.var_facility_id.get().strip()
        csv_path = ROOT / 'facilities' / fid / 'reading_dictionary.csv'
        try:
            out = apply_readings(self.var_dict_test_in.get(), csv_path)
            self.var_dict_test_out.set(out)
        except Exception as exc:
            messagebox.showerror('エラー', str(exc), parent=self)

    def _tab_apis(self):
        frame = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(frame, text='4. API・外部連携')
        frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(frame, text='デモモード（APIを使わず固定FAQのみで応答）', variable=self.var_demo_mode).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=4
        )

        g_src = credentials.key_source('gemini') or '未設定'
        e_src = credentials.key_source('ekispert') or '未設定'

        ttk.Label(frame, text=f'Gemini APIキー（現在: {g_src}）').grid(row=1, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
        ttk.Entry(frame, textvariable=self.var_gemini_key, show='*').grid(row=1, column=1, sticky='ew', pady=(4, 0))
        self._hint(frame, '例: AIzaSy...（Google AI Studio で取得。変更しない場合は空欄）', 2)

        ttk.Label(frame, text='Geminiモデル / 最大トークン').grid(row=3, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
        g_sub = ttk.Frame(frame)
        g_sub.grid(row=3, column=1, sticky='ew', pady=(4, 0))
        g_sub.columnconfigure(0, weight=1)
        default_models = [m for m in (self.var_gemini_model.get(), 'gemini-3.5-flash-lite', 'gemini-2.5-flash', 'gemini-2.5-flash-lite') if m]
        self.gemini_model_combo = ttk.Combobox(g_sub, textvariable=self.var_gemini_model, values=list(dict.fromkeys(default_models)))
        self.gemini_model_combo.grid(row=0, column=0, sticky='ew')
        ttk.Button(g_sub, text='最新モデルを取得', command=self._fetch_gemini_models).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(g_sub, text='最大長:').grid(row=0, column=2, padx=(8, 4))
        ttk.Entry(g_sub, textvariable=self.var_max_tokens, width=8).grid(row=0, column=3)
        self._hint(frame, '例: gemini-3.5-flash-lite / 「最新モデルを取得」でAPIから利用可能なモデルをプルダウンに読み込みます', 4)

        ttk.Checkbutton(frame, text='Google検索を有効にする', variable=self.var_google_search).grid(
            row=5, column=0, columnspan=2, sticky='w', pady=4
        )
        ttk.Checkbutton(frame, text='天気予報（Open-Meteo）を有効にする', variable=self.var_weather).grid(
            row=6, column=0, columnspan=2, sticky='w', pady=4
        )
        ttk.Checkbutton(frame, text='乗り換え案内（駅すぱあと）を有効にする', variable=self.var_transit).grid(
            row=7, column=0, columnspan=2, sticky='w', pady=4
        )

        ttk.Label(frame, text='駅すぱあとプラン').grid(row=8, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
        ttk.Combobox(frame, textvariable=self.var_transit_plan, values=['free', 'standard'], state='readonly').grid(
            row=8, column=1, sticky='w', pady=(4, 0)
        )
        self._hint(frame, '例: free（無料リンク生成） / standard（詳細経路の音声案内に対応）', 9)

        ttk.Label(frame, text=f'駅すぱあとAPIキー（現在: {e_src}）').grid(row=10, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
        ttk.Entry(frame, textvariable=self.var_ekispert_key, show='*').grid(row=10, column=1, sticky='ew', pady=(4, 0))
        self._hint(frame, '例: 駅すぱあとWebサービスのアクセスキー（乗換案内を使わない場合は空欄）', 11)

        ttk.Label(frame, text='キーの保存方法').grid(row=12, column=0, sticky='w', pady=6, padx=(0, 10))
        storage_frame = ttk.Frame(frame)
        storage_frame.grid(row=12, column=1, sticky='w', pady=6)
        ttk.Radiobutton(storage_frame, text='Windows暗号化 (DPAPI)', variable=self.var_key_storage, value='dpapi').pack(side='left')
        ttk.Radiobutton(storage_frame, text='.env ファイルへ保存', variable=self.var_key_storage, value='dotenv').pack(side='left', padx=12)

        log_row = ttk.Frame(frame)
        log_row.grid(row=13, column=0, columnspan=2, sticky='w', pady=6)
        ttk.Checkbutton(log_row, text='会話ログを保存する（runtime/conversations/）', variable=self.var_save_conversation).pack(side='left')
        ttk.Button(log_row, text='ログフォルダを開く', command=self._open_logs_folder).pack(side='left', padx=12)

    def _tab_character_voice(self):
        frame = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(frame, text='5. キャラ・音声・ソフト')
        frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(frame, text='MMDAgent-EX 連携を有効にする', variable=self.var_mmd_enabled).grid(
            row=0, column=0, columnspan=3, sticky='w', pady=4
        )

        ttk.Label(frame, text='MMDキャラクターモデル').grid(row=1, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
        models = app.list_mmd_models()
        ttk.Combobox(frame, textvariable=self.var_mmd_model, values=models, state='readonly').grid(
            row=1, column=1, columnspan=2, sticky='ew', pady=(4, 0)
        )
        self._hint(frame, '例: assets/mmd/gene/Gene.pmd または assets/mmd/uka/MS_Uka.pmd', 2, columnspan=2)

        ttk.Label(frame, text='COEIROINK URL').grid(row=3, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
        ttk.Entry(frame, textvariable=self.var_coeiro_url).grid(row=3, column=1, sticky='ew', pady=(4, 0))
        ttk.Button(frame, text='起動中COEIROINKから話者取得', command=self._fetch_speakers).grid(
            row=3, column=2, padx=(8, 0), pady=(4, 0)
        )
        self._hint(frame, '例: http://127.0.0.1:50032', 4, columnspan=2)

        ttk.Label(frame, text='話者プリセット選択').grid(row=5, column=0, sticky='w', pady=6, padx=(0, 10))
        self.speaker_combo = ttk.Combobox(frame, state='readonly')
        self.speaker_combo.grid(row=5, column=1, columnspan=2, sticky='ew', pady=6)
        self.speaker_combo.bind('<<ComboboxSelected>>', self._on_speaker_selected)

        ttk.Label(frame, text='話者UUID (speaker_uuid)').grid(row=6, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
        ttk.Entry(frame, textvariable=self.var_speaker_uuid).grid(row=6, column=1, columnspan=2, sticky='ew', pady=(4, 0))
        self._hint(frame, '例: 3c37646f-3881-5374-2a83-149267990abc（つくよみちゃん）', 7, columnspan=2)

        ttk.Label(frame, text='スタイルID / 話速').grid(row=8, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
        sub = ttk.Frame(frame)
        sub.grid(row=8, column=1, columnspan=2, sticky='w', pady=(4, 0))
        ttk.Entry(sub, textvariable=self.var_style_id, width=8).pack(side='left')
        ttk.Label(sub, text='話速:').pack(side='left', padx=(12, 4))
        ttk.Entry(sub, textvariable=self.var_speed, width=8).pack(side='left')
        self._hint(frame, '例: スタイルID 0 / 話速 1.1', 9, columnspan=2)

        ttk.Label(frame, text='音声クレジット表記').grid(row=10, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
        ttk.Entry(frame, textvariable=self.var_coeiro_credit).grid(row=10, column=1, columnspan=2, sticky='ew', pady=(4, 0))
        self._hint(frame, '例: COEIROINK:つくよみちゃん', 11, columnspan=2)

        ttk.Label(frame, text='COEIROINKv2.exe').grid(row=12, column=0, sticky='w', pady=6, padx=(0, 10))
        ttk.Entry(frame, textvariable=self.var_coeiro_exe).grid(row=12, column=1, sticky='ew', pady=6)
        ttk.Button(frame, text='参照', command=lambda: self._browse_exe(self.var_coeiro_exe, 'COEIROINKv2.exe')).grid(
            row=12, column=2, padx=(8, 0), pady=6
        )

        ttk.Label(frame, text='MMDAgent-EX.exe').grid(row=13, column=0, sticky='w', pady=6, padx=(0, 10))
        ttk.Entry(frame, textvariable=self.var_mmd_exe).grid(row=13, column=1, sticky='ew', pady=6)
        ttk.Button(frame, text='参照', command=lambda: self._browse_exe(self.var_mmd_exe, 'MMDAgent-EX.exe')).grid(
            row=13, column=2, padx=(8, 0), pady=6
        )

        ttk.Label(frame, text='MMDウィンドウサイズ').grid(row=14, column=0, sticky='w', pady=(4, 0), padx=(0, 10))
        ttk.Entry(frame, textvariable=self.var_mmd_window_size, width=16).grid(row=14, column=1, sticky='w', pady=(4, 0))
        self._hint(frame, '例: 900,720（幅,高さ）', 15, columnspan=2)

    def _fetch_gemini_models(self):
        key = self.var_gemini_key.get().strip() or credentials.get_key('gemini')
        try:
            models = fetch_gemini_models(key)
        except Exception as exc:
            messagebox.showerror('取得失敗', str(exc), parent=self)
            return
        if not models:
            messagebox.showwarning('取得結果', '利用可能なGeminiモデルが見つかりませんでした。', parent=self)
            return
        self.gemini_model_combo['values'] = models
        if self.var_gemini_model.get() not in models:
            self.var_gemini_model.set(models[0])
        messagebox.showinfo('取得完了', f'{len(models)}件のモデルをプルダウンに読み込みました。', parent=self)

    def _prev_tab(self):
        idx = self.notebook.index(self.notebook.select())
        if idx > 0:
            self.notebook.select(idx - 1)

    def _next_tab(self):
        idx = self.notebook.index(self.notebook.select())
        if idx < self.notebook.index('end') - 1:
            self.notebook.select(idx + 1)

    def _open_logs_folder(self):
        target = ROOT / 'runtime' / 'conversations'
        target.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(str(target))

    def _open_docs_folder(self):
        fid = self.var_facility_id.get().strip()
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', fid):
            messagebox.showwarning('確認', '有効な施設IDを入力してください。', parent=self)
            return
        target = ROOT / 'facilities' / fid / 'docs'
        target.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(str(target))

    def _browse_exe(self, var, label):
        selected = filedialog.askopenfilename(
            parent=self, title=f'{label} を選択', filetypes=[('実行ファイル', '*.exe')]
        )
        if selected:
            var.set(str(Path(selected).resolve()))

    def _fetch_speakers(self):
        try:
            speakers = app.fetch_coeiroink_speakers({'coeiroink': {'url': self.var_coeiro_url.get().strip()}})
        except Exception:
            messagebox.showerror(
                '取得失敗',
                'COEIROINKから話者一覧を取得できませんでした。COEIROINKを起動してから再試行してください。',
                parent=self,
            )
            return
        self.speaker_choices = []
        labels = []
        for s in speakers:
            for st in s.get('styles', []):
                self.speaker_choices.append({
                    'name': s['speakerName'],
                    'uuid': s['speakerUuid'],
                    'style_name': st['styleName'],
                    'style_id': st['styleId'],
                })
                labels.append(f"{s['speakerName']} ({st['styleName']})")
        self.speaker_combo['values'] = labels
        if labels:
            cur_uuid = self.var_speaker_uuid.get().strip()
            cur_style = self.var_style_id.get().strip()
            matched = next(
                (i for i, c in enumerate(self.speaker_choices)
                 if c['uuid'] == cur_uuid and str(c['style_id']) == cur_style),
                0,
            )
            self.speaker_combo.current(matched)
            self._on_speaker_selected()
            messagebox.showinfo('取得完了', f'{len(labels)}件の話者スタイルを取得しました。', parent=self)

    def _on_speaker_selected(self, _event=None):
        idx = self.speaker_combo.current()
        if 0 <= idx < len(self.speaker_choices):
            choice = self.speaker_choices[idx]
            self.var_speaker_uuid.set(choice['uuid'])
            self.var_style_id.set(str(choice['style_id']))
            self.var_coeiro_credit.set(f"COEIROINK:{choice['name']}")

    def _save(self):
        fid = self.var_facility_id.get().strip()
        if fid == 'sample':
            proceed = messagebox.askyesno(
                '公開用テンプレートの保護確認',
                '施設ID「sample」はGitHub公開用の素のテンプレートです。\n'
                'テストや独自施設の設定は、別の施設ID（例: test_01）にして保存することをおすすめします。\n\n'
                'このまま「sample」を上書き保存しますか？（「いいえ」を押すと入力画面に戻ります）',
                parent=self,
            )
            if not proceed:
                return
        payload = {
            'facility_id': self.var_facility_id.get(),
            'facility_name': self.var_facility_name.get(),
            'greeting': self.var_greeting.get(),
            'persona': self.var_persona.get(),
            'city': self.var_city.get(),
            'nearest_station': self.var_station.get(),
            'demo_mode': self.var_demo_mode.get(),
            'gemini_model': self.var_gemini_model.get(),
            'max_output_tokens': self.var_max_tokens.get(),
            'enable_google_search': self.var_google_search.get(),
            'weather_enabled': self.var_weather.get(),
            'transit_enabled': self.var_transit.get(),
            'transit_plan': self.var_transit_plan.get(),
            'key_storage': self.var_key_storage.get(),
            'gemini_key': self.var_gemini_key.get(),
            'ekispert_key': self.var_ekispert_key.get(),
            'mmd_enabled': self.var_mmd_enabled.get(),
            'mmd_model_path': self.var_mmd_model.get(),
            'mmd_window_size': self.var_mmd_window_size.get(),
            'coeiroink_url': self.var_coeiro_url.get(),
            'speaker_uuid': self.var_speaker_uuid.get(),
            'style_id': self.var_style_id.get(),
            'speed': self.var_speed.get(),
            'coeiroink_credit': self.var_coeiro_credit.get(),
            'coeiroink_exe': self.var_coeiro_exe.get(),
            'mmd_exe': self.var_mmd_exe.get(),
            'save_conversation': self.var_save_conversation.get(),
        }
        try:
            apply_setup(payload)
            self._refresh_facility_related_views()
            self.var_existing_facility.set(fid)
        except Exception as exc:
            messagebox.showerror('保存エラー', str(exc), parent=self)
            return
        if messagebox.askyesno('保存完了', '全体設定を保存しました。このまま観光案内を起動しますか？（「いいえ」で編集を続けられます）', parent=self):
            self.destroy()
            subprocess.Popen(['cmd', '/c', str(ROOT / 'start.bat')], cwd=str(ROOT))


if __name__ == '__main__':
    SetupWizard().mainloop()
