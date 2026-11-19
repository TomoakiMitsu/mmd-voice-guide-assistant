# 観光案内アシスタント（汎用テンプレート版）

施設ごとに案内設定・資料・MMDキャラクター・合成音声・API設定を差し替えられる、Windows向けローカル観光案内アシスタントの汎用テンプレートです。

## 特徴
- Python標準ライブラリのみで動作（追加pipパッケージ不要）
- 音声入力（Web Speech API）→ 文字起こし → Gemini回答生成（ツール連携可）→ COEIROINK音声合成 → MMDAgent-EX口パク再生 → 終了後即マイク再開
- 複数ターンの会話履歴保持（ブラウザメモリ上に直近6往復）および処理段階ごとの経過時間表示
- 施設ごとの設定・資料・読み辞書を `facilities/<施設ID>/` に分離
- 管理者による一括設定（`config.json` + `.env` または Windows DPAPI 暗号化保存）

---

## フォルダ構成とカスタマイズ対象

```
.
├── config.example.json       # 管理者設定テンプレート（コピーして config.json を作成）
├── .env.example              # APIキー一括設定テンプレート（コピーして .env を作成）
├── start.bat                 # ワンクリック起動（launcher.py を実行）
├── app.py                    # HTTPサーバー・会話制御・MMD/COEIROINK連携
├── credentials.py            # APIキー管理（DPAPI > .env > 環境変数）
├── services.py               # Gemini外部ツール・Open-Meteo・駅すぱあと
├── route_directions.py       # 駅すぱあと詳細経路の読み上げ文変換
├── reading_dictionary.py     # 施設固有の読み辞書適用
├── assets/mmd/
│   ├── gene/                 # 初期同梱モデル1: Gene（CC BY 4.0）
│   └── uka/                  # 初期同梱モデル2: Uka（CC BY 4.0）
├── facilities/
│   └── sample/               # 素のサンプル施設（コピーして独自施設を作成）
│       ├── facility.json     # 施設名・挨拶・口調・地域・デモFAQ・上書き設定
│       ├── reading_dictionary.csv  # 読み辞書（表記,読み）
│       ├── verified_routes.json    # 確認済み経路（任意）
│       └── docs/             # 施設資料（.md / .txt / .json）を配置
└── web/index.html            # ブラウザUI
```

---

## 管理者向け一括セットアップ手順

### 1. APIキーの設定（`.env` または 画面からのDPAPI保存）
1. `.env.example` をコピーして `.env` を作成し、`GEMINI_API_KEY`（および必要なら `EKISPERT_API_KEY`）を記入します。
2. または、起動後にブラウザ画面の「Gemini APIキー設定」「外部API・音声設定確認」から入力すると、Windows DPAPI で暗号化保存（`runtime/*.dpapi`）されます。
3. キーの優先順位は **Windows DPAPI > `.env` > OS環境変数** です。復号したキーは画面・ログに出力されません。

### 2. 全体設定（`config.json`）
初回起動時に `config.example.json` から `config.json` が自動生成されます。手動で事前にコピーして編集することもできます。

- `facility`: 使用する施設フォルダ名（例: `"sample"` → `facilities/sample/` を参照）
- `demo_mode`: `false` にするとGeminiを使用、`true` なら固定FAQのみ応答
- `gemini`: `model`（例: `"gemini-3.5-flash-lite"`）、`max_output_tokens`、`enable_google_search`
- `external_apis`: `weather_enabled`、`transit_enabled`、`transit_plan`（`"free"` または `"standard"`）
- `mmd`: 使用するMMDモデルやモーションを指定
- `coeiroink`: 使用する合成音声の話者UUID・スタイルID・話速・クレジットを指定

### 3. 施設独自の設定・資料の作成
`facilities/sample/` をコピーして `facilities/<新しい施設ID>/`（英数字・ハイフン・アンダースコア）を作成し、`config.json` の `"facility"` を変更します。

1. `facility.json`: 施設名（`name`）、挨拶（`greeting`）、口調（`persona`）、所在地（`location`）、デモFAQ（`knowledge`）、注意事項（`notes`）を設定します。
   - 施設ごとにMMDモデルやCOEIROINK話者を変えたい場合は、`facility.json` 内に `"mmd": {...}` や `"coeiroink": {...}` を書くと `config.json` の設定を上書きできます。
2. `docs/`: 案内資料（`.md`, `.txt`, `.json`、UTF-8、1ファイル150KB以内・合計4万文字以内）を置きます。`_` で始まるファイル・フォルダはGeminiへ送信されません。
3. `reading_dictionary.csv`: `表記,読み` の2列CSV（UTF-8）。COEIROINKへの送信文のみ置換します。

### 4. MMDキャラクターの差し替え（Gene / Uka / 任意モデル）
`assets/mmd/` に `gene` と `uka` の両方を同梱しています。`config.json`（または `facility.json`）の `mmd` セクションを変更し、`start.bat`（または `app.py`）を起動すると、`guide.fst` と `guide.mdf` が自動生成されます。

例：Uka に切り替える場合：
```json
"mmd": {
  "enabled": true,
  "model_path": "assets/mmd/uka/MS_Uka.pmd",
  "idle_motion": "assets/mmd/uka/motion/stand.vmd",
  "thinking_motion": "assets/mmd/uka/motion/16_thinking.vmd",
  "credit": "MS_Uka (c) Nagoya Institute of Technology (CC BY 4.0)"
}
```
任意のフリーMMDモデルを追加する場合は、`assets/mmd/<モデル名>/` に配置して `model_path` 等を指定してください（MMDAgent-EXで口パクを動かす場合は、モデルに対応した `.shapemap` やモーションも合わせて配置してください）。

### 5. 合成音声（COEIROINK）の種類の設定
COEIROINKを起動した状態でブラウザ画面の「外部API・音声設定確認」→「COEIROINK話者一覧を取得」を押すと、導入済み話者の `speakerUuid` と `styleId` の一覧が表示されます。その値を `config.json`（または施設別 `facility.json`）の `coeiroink` に設定してください。

---

## 起動方法
1. Python 3.11以降、COEIROINK v2、MMDAgent-EX を用意します。
2. `start.bat` をダブルクリックします（初回のみCOEIROINK・MMDAgent-EXの実行ファイル選択画面が出ます）。
3. ブラウザで `http://127.0.0.1:8765` が開きます（音声入力は Chrome / Edge 推奨）。

---

## GitHub公開時の注意
`.gitignore` により以下は自動的に除外されます。
- `.env`（APIキー一括設定ファイル）
- `config.json`（環境別設定ファイル）
- `launcher.local.json`（PC固有パス）
- `runtime/`（DPAPI暗号化キー、ログ、一時WAV）
- `dist/`、`__pycache__/`、`*.key`、`*.dpapi`

`facilities/` に非公開の施設資料を追加した場合は、公開前に削除するか `.gitignore` に追加してください。

---

## 単体テスト
```powershell
python -m unittest discover -s tests -v
```
