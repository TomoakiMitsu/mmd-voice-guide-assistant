"""Windows one-click launcher. Machine paths stay outside portable configuration."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.request

import app

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / 'launcher.local.json'


def log_line(message):
    try:
        (ROOT / 'runtime').mkdir(exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with (ROOT / 'runtime' / 'launcher.log').open('a', encoding='utf-8') as f:
            f.write(f'[{stamp}] {message}\n')
    except OSError:
        pass


def load_paths():
    if LOCAL.exists():
        return json.loads(LOCAL.read_text(encoding='utf-8-sig'))
    return {}


def find_executable(kind, saved):
    configured = saved.get(kind, '')
    if configured and Path(configured).is_file():
        return Path(configured).resolve()
    patterns = {'coeiroink': ('*COEIROINK*.exe', '*coeiroink*.exe'),
                'mmd': ('*MMDAgent*.exe',)}[kind]
    bases = [ROOT / 'software', ROOT.parent / 'software']
    for base in bases:
        if base.is_dir():
            for pattern in patterns:
                for candidate in sorted(base.rglob(pattern)):
                    if not any(word in candidate.name.lower() for word in ('uninstall', 'setup', 'installer')):
                        return candidate.resolve()
    return None


def http_ready(url):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=1) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def mmd_connected():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:8765/api/info', timeout=1) as response:
            return bool(json.load(response).get('mmd_connected'))
    except (OSError, ValueError):
        return False


def wait_ready(check, timeout, tick=lambda: None):
    deadline = time.monotonic() + timeout
    while True:
        if check():
            return
        if time.monotonic() >= deadline:
            raise TimeoutError('起動待ちがタイムアウトしました。ソフトの画面と設定を確認してください。')
        tick()
        time.sleep(0.3)


def launch(executable, arguments=(), cwd=None, log_name=None):
    kwargs = {'cwd': str(cwd or Path(executable).parent)}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    if log_name:
        (ROOT / 'runtime').mkdir(exist_ok=True)
        with (ROOT / 'runtime' / log_name).open('ab') as log:
            return subprocess.Popen([str(executable), *map(str, arguments)],
                                    stdout=log, stderr=log, **kwargs)
    return subprocess.Popen([str(executable), *map(str, arguments)], **kwargs)


def enable_mmd():
    path = ROOT / 'config.json'
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    config.setdefault('mmd', {})['enabled'] = True
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run():
    import tkinter as tk
    from tkinter import filedialog, messagebox

    log_line('launcher start')
    root = tk.Tk()
    root.title('観光案内を起動しています')
    root.geometry('500x150')
    root.resizable(False, False)
    root.lift()
    root.attributes('-topmost', True)
    status = tk.StringVar(value='起動環境を確認しています…')
    tk.Label(root, textvariable=status, wraplength=460, padx=20, pady=35,
             font=('Yu Gothic UI', 11)).pack()
    root.update()

    def report(text):
        log_line(text)
        status.set(text)
        root.update()

    def choose(kind, label, paths):
        exe = find_executable(kind, paths)
        if exe is None:
            report(f'初回設定: {label}の実行ファイルを選択してください。')
            selected = filedialog.askopenfilename(parent=root,
                title=f'{label}の実行ファイルを選択', filetypes=[('実行ファイル', '*.exe')])
            if not selected:
                raise RuntimeError(f'{label}の場所が未設定です。導入済みの実行ファイルを選んで再実行してください。')
            exe = Path(selected).resolve()
        paths[kind] = str(exe)
        LOCAL.write_text(json.dumps(paths, ensure_ascii=False, indent=2), encoding='utf-8')
        return exe

    try:
        config, _ = app.settings()
        app.sync_mmd_files(config)
        paths = load_paths()
        if not http_ready('http://127.0.0.1:8765/api/info'):
            report('観光案内アプリを起動しています…')
            launch(sys.executable, [ROOT / 'app.py'], cwd=ROOT, log_name='server.log')
            wait_ready(lambda: http_ready('http://127.0.0.1:8765/api/info'), 15, root.update)
        coeiro_url = config['coeiroink']['url'].rstrip('/')
        if not http_ready(coeiro_url + '/v1/speakers'):
            exe = choose('coeiroink', 'COEIROINK', paths)
            report('COEIROINKを起動しています…（最大90秒）')
            launch(exe)
            wait_ready(lambda: http_ready(coeiro_url + '/v1/speakers'), 90, root.update)

        if not mmd_connected():
            exe = choose('mmd', 'MMDAgent-EX', paths)
            model_rel = config['mmd'].get('model_path', 'assets/mmd/gene/Gene.pmd')
            if not (ROOT / model_rel).is_file():
                raise RuntimeError(f'MMDモデルが見つかりません: {model_rel}')
            report('MMDAgent-EXと案内キャラクターを起動しています…')
            process = launch(exe, [ROOT / 'guide.mdf'], cwd=exe.parent, log_name='mmd.log')

            def mmd_is_ready():
                if process.poll() is not None:
                    raise RuntimeError(f'MMDAgent-EXが終了しました（コード {process.returncode}）。runtime/mmd.log を確認してください。')
                return mmd_connected()

            wait_ready(mmd_is_ready, 90, root.update)
        enable_mmd()

        if not http_ready('http://127.0.0.1:8765/api/info'):
            report('観光案内アプリを起動しています…')
            launch(sys.executable, [ROOT / 'app.py'], cwd=ROOT, log_name='server.log')
            wait_ready(lambda: http_ready('http://127.0.0.1:8765/api/info'), 15, root.update)
        report('案内画面を開いています…')
        os.startfile('http://127.0.0.1:8765')
        log_line('launcher finished successfully')
    except Exception as exc:
        log_line(f'launcher error: {exc}\n{traceback.format_exc()}')
        messagebox.showerror('起動できませんでした', str(exc), parent=root)
        return 1
    finally:
        root.destroy()
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='ソフトの検出のみ（起動しない）')
    args = parser.parse_args()
    if args.check:
        paths = load_paths()
        for kind in ('coeiroink', 'mmd'):
            print(f"{kind}: {find_executable(kind, paths) or '初回起動時に選択'}")
    else:
        (ROOT / 'runtime').mkdir(exist_ok=True)
        with (ROOT / 'runtime/launcher.lock').open('a+b') as lock:
            if os.name == 'nt':
                import msvcrt
                lock.seek(0)
                if not lock.read(1):
                    lock.write(b'0')
                    lock.flush()
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    sys.exit(0)
            sys.exit(run())
