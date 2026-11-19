"""API key management: Windows DPAPI > .env file > OS environment variables."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY_PATH = ROOT / 'runtime/gemini.dpapi'
ENV_PATH = ROOT / '.env'


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('画面からのキー保存はWindowsに対応しています。.envまたは環境変数を利用してください。')
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    target = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('キーを暗号化・復号できません。このPCでキーを設定し直してください。')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def key_path(service):
    if service not in ('gemini', 'ekispert'):
        raise ValueError('APIサービスが不正です')
    return KEY_PATH if service == 'gemini' else KEY_PATH.with_name('ekispert.dpapi')


def load_dotenv(path=None):
    target = path or ENV_PATH
    values = {}
    if not target.is_file():
        return values
    for raw_line in target.read_text(encoding='utf-8-sig').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        if k:
            values[k] = v
    return values


def validate_key(key):
    if not isinstance(key, str) or not 15 <= len(key.strip()) <= 256 or any(c.isspace() for c in key.strip()):
        raise ValueError('APIキーの形式を確認してください。')
    return key.strip()


def save_key(key, service='gemini'):
    cleaned = validate_key(key)
    encrypted = crypt(cleaned.encode('utf-8'))
    path = key_path(service)
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(encrypted)
    temporary.replace(path)


def get_key(service='gemini'):
    path = key_path(service)
    if path.exists():
        return crypt(path.read_bytes(), decrypt=True).decode('utf-8')
    env_name = 'GEMINI_API_KEY' if service == 'gemini' else 'EKISPERT_API_KEY'
    dotenv_val = load_dotenv().get(env_name, '')
    if dotenv_val:
        return dotenv_val
    return os.environ.get(env_name, '')


def key_source(service='gemini'):
    """Return where the active key is configured without revealing the key."""
    if key_path(service).exists():
        return 'dpapi'
    env_name = 'GEMINI_API_KEY' if service == 'gemini' else 'EKISPERT_API_KEY'
    if load_dotenv().get(env_name):
        return 'dotenv'
    if os.environ.get(env_name):
        return 'env'
    return None
