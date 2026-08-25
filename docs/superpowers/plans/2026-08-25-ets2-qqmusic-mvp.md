# 欧卡2 QQ音乐伴侣播放器 MVP 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 Windows 外部伴侣程序（Python），支持 QQ 音乐扫码登录，浏览/播放自建与收藏歌单及"我喜欢"，通过本地 HTTP mp3 流注册为欧卡2车载网络电台，实现游戏内听歌 + 全局热键切歌/收藏。

**Architecture:** 核心是无界面依赖的 Python 包 `qqm`：QQ 音乐 Web 接口客户端（移植自已实机验证的 Spica 实现）+ 播放队列状态机 + ffmpeg 转码的本地流服务器。游戏侧零侵入——只读写 `Documents\Euro Truck Simulator 2\live_streams.sii` 注册电台条目。所有网络测试离线 mock。

**Tech Stack:** Python 3.10+，运行时零第三方依赖（纯标准库 urllib/json/http.server/threading）；外部二进制仅 `ffmpeg`；可选 `keyboard`（全局热键）；测试 pytest。

---

## 背景与参考实现（执行者必读）

本计划的登录与播放接口代码**不是从零逆向**。以下参考已经实机验证（2026-08 冒烟通过），遇到字段/流程疑问优先对照：

| 参考 | 内容 |
|---|---|
| `[已移除本地私有路径]\agent_tools\function_tools\song\qqmusic.py` | **权威参考**：扫码登录全流程、搜索、播放直链、凭证持久化（stdlib-only） |
| `[已移除本地私有路径]\docs\交接-QQ音乐源接入-2026-08-14.md` | 端点、参数、品质前缀、风控纪律 |
| `[已移除本地私有路径]\docs\superpowers\specs\2026-08-14-qqmusic-login-renew-design.md` | 登录过期状态机设计 |
| https://raw.githubusercontent.com/L-1124/QQMusicApi/main/qqmusic_api/modules/songlist.py | 歌单写操作 param 的权威定义 |

关键事实：

- 播放走 `POST https://u.y.qq.com/cgi-bin/musicu.fcg` 的 `vkey.GetVkeyServer/CgiGetVkey` → `sip[0]+purl`，返回明文 MP3/M4A 直链，无 qmc 加密。VIP 歌必须带登录 Cookie（匿名 purl 为空）。
- 品质映射：`320`→`M800{mid}{mid}.mp3`（默认）、`128`→`M500..mp3`、`m4a`→`C400..m4a`。
- 必带请求头 `Referer: https://y.qq.com/` 与桌面 UA；必须绕过系统代理直连（`ProxyHandler({})`）。
- 风控纪律：一首歌只请求一次 vkey、失败最多重试 1 次、失败即报错不静默重试放大。
- 扫码登录轮询状态码语义：66=已扫待确认、65=二维码失效、68=拒绝、0=成功（参考实现的注释里另有 67 的说法，以"非 0/65/68 即继续等待或报错"处理）。

## 明确不在本计划范围（后续独立计划）

- 游戏内 ImGui 插件（SPF-Framework/hry-core，C++）
- 播放上报计入手机端最近播放（需先抓包 PoC）
- 凭证自动续期（当前策略：过期→重新扫码）
- 本地直接出声模式（调试用 VLC/浏览器打开流地址即可）

## 文件结构

```
F:\research\ets2-qqmusic\
├── pyproject.toml              # 项目元数据 + pytest 配置
├── requirements-dev.txt        # pytest
├── README.md
├── .gitignore                  # data/ 等
├── docs\superpowers\plans\     # 本计划
├── qqm\
│   ├── __init__.py
│   ├── models.py               # Song / Playlist 数据类
│   ├── config.py               # 数据目录、sii 路径探测、端口、prefs
│   ├── qqmusic_api.py          # 登录/搜索/播放直链/凭证持久化（移植 Spica）
│   ├── library.py              # 歌单列表/详情/我喜欢/收藏写操作
│   ├── queue_logic.py          # 播放队列纯逻辑（顺序/循环/随机）
│   ├── stream_server.py        # RingBuffer + TrackStreamer(ffmpeg) + HTTP + RadioApp
│   ├── radio_config.py         # live_streams.sii 解析/备份/注册/移除
│   ├── hotkeys.py              # 可选全局热键
│   └── cli.py                  # argparse 入口
└── tests\
    ├── conftest.py             # FakeOpener/FakeResponse
    ├── test_smoke.py
    ├── test_config.py
    ├── test_qqmusic_api.py
    ├── test_library.py
    ├── test_queue_logic.py
    ├── test_stream_server.py
    ├── test_radio_config.py
    ├── test_hotkeys.py
    └── test_cli.py
```

---

### Task 1: 项目脚手架

**Files:**
- Create: `F:\research\ets2-qqmusic\pyproject.toml`
- Create: `F:\research\ets2-qqmusic\requirements-dev.txt`
- Create: `F:\research\ets2-qqmusic\.gitignore`
- Create: `F:\research\ets2-qqmusic\qqm\__init__.py`
- Create: `F:\research\ets2-qqmusic\tests\test_smoke.py`

- [ ] **Step 1: 创建目录并 git init**

```powershell
New-Item -ItemType Directory -Force -Path "F:\research\ets2-qqmusic\qqm","F:\research\ets2-qqmusic\tests","F:\research\ets2-qqmusic\docs\superpowers\plans" | Out-Null
Set-Location "F:\research\ets2-qqmusic"; git init
```

- [ ] **Step 2: 写配置文件**

`pyproject.toml`:
```toml
[project]
name = "qqm"
version = "0.1.0"
description = "ETS2 QQ Music companion player"
requires-python = ">=3.10"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

`requirements-dev.txt`:
```
pytest>=8
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
data/
dist/
```

`qqm/__init__.py`:
```python
"""ETS2 QQ 音乐伴侣播放器."""
```

- [ ] **Step 3: 写冒烟测试**

`tests/test_smoke.py`:
```python
import qqm


def test_package_importable():
    assert qqm.__doc__
```

- [ ] **Step 4: 安装依赖并运行测试**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pip install -r requirements-dev.txt; python -m pytest`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "chore: scaffold qqm project"
```

---

### Task 2: models.py 与 config.py

**Files:**
- Create: `F:\research\ets2-qqmusic\qqm\models.py`
- Create: `F:\research\ets2-qqmusic\qqm\config.py`
- Create: `F:\research\ets2-qqmusic\tests\test_config.py`

- [ ] **Step 1: 写 models.py（纯数据类，无需先行测试）**

`qqm/models.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Song:
    """一首歌。mid 用于取播放链接，songid 用于收藏写操作。"""

    mid: str
    songid: int
    title: str
    artists: list[str] = field(default_factory=list)
    album: str = ""
    duration: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def artist_text(self) -> str:
        return ", ".join(a for a in self.artists if a)

    def display_name(self) -> str:
        return f"{self.title} - {self.artist_text}" if self.artist_text else self.title


@dataclass
class Playlist:
    pid: int
    name: str
    count: int
    kind: str  # "created" | "fav"
```

- [ ] **Step 2: 写失败测试**

`tests/test_config.py`:
```python
import json

from qqm import config


def test_paths_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("QQM_DATA_DIR", str(tmp_path))
    cfg = config.Config.load()
    assert cfg.data_dir == tmp_path
    assert cfg.cookie_path == tmp_path / "qqmusic_cookie.json"
    assert cfg.qr_path == tmp_path / "qqmusic_qr.png"


def test_sii_path_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("QQM_SII_PATH", str(tmp_path / "live_streams.sii"))
    cfg = config.Config.load()
    assert cfg.sii_path == tmp_path / "live_streams.sii"


def test_default_sii_path_points_to_documents(monkeypatch):
    monkeypatch.delenv("QQM_SII_PATH", raising=False)
    cfg = config.Config.load()
    assert cfg.sii_path.name == "live_streams.sii"


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("QQM_DATA_DIR", str(tmp_path))
    cfg = config.Config.load()
    assert cfg.stream_port == 23456
    assert cfg.quality == "320"


def test_prefs_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("QQM_DATA_DIR", str(tmp_path))
    cfg = config.Config.load()
    cfg.save_prefs({"last_playlist": "123"})
    raw = json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))
    assert raw["last_playlist"] == "123"
    assert config.Config.load().load_prefs()["last_playlist"] == "123"


def test_documents_dir_resolves(tmp_path, monkeypatch):
    monkeypatch.delenv("QQM_DOCUMENTS_DIR", raising=False)
    d = config.documents_dir()
    assert d  # Windows 上应解析出真实文档目录
```

- [ ] **Step 3: 运行确认失败**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_config.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现 config.py**

`qqm/config.py`:
```python
from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_CSIDL_PERSONAL = 5  # 文档目录


def documents_dir() -> str:
    """解析真实「文档」目录（兼容 OneDrive 重定向）。"""
    env = os.environ.get("QQM_DOCUMENTS_DIR")
    if env:
        return env
    buf = ctypes.create_unicode_buffer(512)
    hr = ctypes.windll.shell32.SHGetFolderPathW(None, _CSIDL_PERSONAL, None, 0, buf)
    if hr != 0:
        return str(Path.home() / "Documents")
    return buf.value


@dataclass
class Config:
    data_dir: Path
    stream_port: int = 23456
    quality: str = "320"
    sii_path: Path = field(default_factory=lambda: Path())

    @classmethod
    def load(cls) -> "Config":
        data_dir = Path(os.environ.get("QQM_DATA_DIR", str(Path.cwd() / "data")))
        sii_env = os.environ.get("QQM_SII_PATH")
        sii = (
            Path(sii_env)
            if sii_env
            else Path(documents_dir()) / "Euro Truck Simulator 2" / "live_streams.sii"
        )
        return cls(
            data_dir=data_dir,
            stream_port=int(os.environ.get("QQM_STREAM_PORT", "23456")),
            quality=os.environ.get("QQM_QUALITY", "320"),
            sii_path=sii,
        )

    @property
    def cookie_path(self) -> Path:
        return self.data_dir / "qqmusic_cookie.json"

    @property
    def qr_path(self) -> Path:
        return self.data_dir / "qqmusic_qr.png"

    @property
    def prefs_path(self) -> Path:
        return self.data_dir / "prefs.json"

    def save_prefs(self, prefs: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.prefs_path.write_text(
            json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_prefs(self) -> dict:
        if not self.prefs_path.exists():
            return {}
        try:
            return json.loads(self.prefs_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
```

- [ ] **Step 5: 运行测试通过**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_config.py -v`
Expected: `6 passed`

- [ ] **Step 6: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "feat: models and config (paths/prefs)"
```

---

### Task 3: qqmusic_api.py — 基础设施（opener/musicu/hash33/凭证持久化）

**Files:**
- Create: `F:\research\ets2-qqmusic\qqm\qqmusic_api.py`
- Create: `F:\research\ets2-qqmusic\tests\conftest.py`
- Create: `F:\research\ets2-qqmusic\tests\test_qqmusic_api.py`

- [ ] **Step 1: 写公共 FakeResponse fixture**

`tests/conftest.py`:
```python
import io


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
```

（测试文件用 `from conftest import FakeResponse` 导入；pytest rootdir 导入模式支持。）

- [ ] **Step 2: 写失败测试**

`tests/test_qqmusic_api.py`:
```python
import json
import urllib.error

import pytest

from conftest import FakeResponse

from qqm import qqmusic_api as api


class TestHash33:
    def test_seed_zero_single_char(self):
        assert api.hash33("x") == 120  # ord('x')=120

    def test_empty_with_gtk_seed(self):
        assert api.hash33("", 5381) == 5381

    def test_masked_31bit(self):
        assert 0 <= api.hash33("qrsig-example-value") <= 2147483647


class TestMaskCredentials:
    def test_masks_cookie_style(self):
        out = api.mask_credentials("uin=o123; qqmusic_key=SECRET; other=ok")
        assert "SECRET" not in out
        assert "other=ok" in out

    def test_masks_json_style(self):
        out = api.mask_credentials('{"musickey": "ABC", "n": 1}')
        assert "ABC" not in out
        assert '"n": 1' in out


class TestPersistence:
    def test_save_load_clear_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api, "login_cookie_path", lambda: tmp_path / "c.json")
        api.save_login("o123", "uin=o123; qqmusic_key=k")
        uin, cookie = api.load_login()
        assert uin == "o123"
        assert "qqmusic_key=k" in cookie
        api.clear_login()
        assert api.load_login() == (None, None)

    def test_extract_uin(self):
        assert api._extract_uin("uin=o42; x=1") == "42"
        assert api._extract_uin("uin=42") == "42"
        assert api._extract_uin("") is None

    def test_corrupt_file_is_anonymous(self, tmp_path, monkeypatch):
        p = tmp_path / "c.json"
        p.write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(api, "login_cookie_path", lambda: p)
        assert api.load_login() == (None, None)


class TestPostMusicu:
    def test_posts_json_and_parses(self, monkeypatch):
        sent = {}

        class Opener:
            def open(self, request, timeout=None):
                sent["url"] = request.full_url
                sent["body"] = json.loads(request.data.decode("utf-8"))
                sent["headers"] = dict(request.header_items())
                return FakeResponse(json.dumps({"code": 0}).encode())

        monkeypatch.setattr(api, "_direct_opener", lambda: Opener())
        data = api._post_musicu({"req": {"module": "m"}}, cookie="uin=o1")
        assert data == {"code": 0}
        assert sent["url"] == api._MUSICU_ENDPOINT
        assert sent["headers"]["Cookie"] == "uin=o1"
        assert sent["headers"]["Referer"] == "https://y.qq.com/"
```

- [ ] **Step 3: 运行确认失败**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_qqmusic_api.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现 qqmusic_api.py 基础部分**

`qqm/qqmusic_api.py`（本 Task 先写到这里；后续 Task 在同文件追加）：
```python
"""QQ 音乐 Web 接口客户端。

移植自 Spica-Chatbot（[已移除本地私有路径]\agent_tools\
function_tools\song\qqmusic.py，2026-08 实机验证可用），上游致谢
copws/qq-music-api 与 L-1124/QQMusicApi。仅供个人学习使用。
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MUSICU_ENDPOINT = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) "
        "Gecko/20100101 Firefox/115.0"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=utf-8",
    "Referer": "https://y.qq.com/",
}


def _direct_opener() -> urllib.request.OpenerDirector:
    # QQ 音乐是国内服务，绝不能跟随系统代理（Clash 等），显式空代理直连。
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


class QqmusicLoginRequired(RuntimeError):
    """需要扫码登录（未登录或凭证过期）。"""


def hash33(text: str, seed: int = 0) -> int:
    value = seed
    for ch in text:
        value += (value << 5) + ord(ch)
    return 2147483647 & value


def mask_credentials(text: str) -> str:
    for key in (
        "qqmusic_key", "musickey", "musicid", "access_token",
        "refresh_token", "refresh_key", "openid",
    ):
        text = re.compile(rf'"{key}"\s*:\s*"[^"]*"').sub(rf'"{key}": "***"', text)
        text = re.compile(rf"(?i){key}=[^;\"'\s]+").sub(rf"{key}=***", text)
    return text


def login_cookie_path() -> Path:
    from .config import Config

    return Config.load().cookie_path


def login_qr_path() -> Path:
    from .config import Config

    return Config.load().qr_path


def load_login() -> tuple[str | None, str | None]:
    path = login_cookie_path()
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cookie = str(data.get("cookie") or "")
        uin = str(data.get("uin") or "")
        if cookie:
            return uin or _extract_uin(cookie), cookie
    except Exception as exc:
        logger.warning("QQ音乐登录态文件损坏，按匿名运行：%s (%s)", path, exc)
    return None, None


def save_login(uin: str, cookie: str) -> Path:
    path = login_cookie_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"uin": uin, "cookie": cookie}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def clear_login() -> None:
    try:
        login_cookie_path().unlink(missing_ok=True)
    except OSError:
        pass


def login_available() -> bool:
    return bool(load_login()[1])


def _extract_uin(cookie: str) -> str | None:
    match = re.search(r"(?:^|;\s*)uin=o?(\d+)", cookie or "")
    return match.group(1) if match else None


def _post_musicu(body: dict[str, Any], cookie: str | None = None, timeout: int = 20) -> dict[str, Any]:
    headers = dict(_BASE_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(
        _MUSICU_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with _direct_opener().open(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
```

注意：`login_cookie_path`/`login_qr_path` 延迟导入 config 是为了让测试能整体 monkeypatch 这两个函数。

- [ ] **Step 5: 运行测试通过**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_qqmusic_api.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "feat(qqm): api base - opener/musicu/hash33/credential store"
```

---

### Task 4: qqmusic_api.py — 扫码登录（移植 qr_login）

**Files:**
- Modify: `F:\research\ets2-qqmusic\qqm\qqmusic_api.py`（追加）
- Modify: `F:\research\ets2-qqmusic\tests\test_qqmusic_api.py`（追加）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_qqmusic_api.py`。要点：用一个脚本化 opener 按端点分发响应，cookie jar 手工预置 `qrsig` 与 `p_skey`，authorize 用 HTTPError(302) 模拟重定向：

```python
import http.cookiejar


def _jar_with(qrsig="QRSIG", pskey="PSKEY"):
    jar = http.cookiejar.CookieJar()

    def _set(name, value, domain):
        c = http.cookiejar.Cookie(
            0, name, value, domain, domain, domain, "/", "/", True, False,
            None, False, None, None, {},
        )
        jar.set_cookie(c)

    _set("qrsig", qrsig, "ssl.ptlogin2.qq.com")
    _set("p_skey", pskey, "graph.qq.com")
    return jar


class TestQrLogin:
    def _scripted_opener(self, jar, tmp_path, recorder):
        redirect = (
            "https://ssl.ptlogin2.graph.qq.com/check_sig?uin=10001"
            "&ptsigx=SIGX&ptredirect=100"
        )
        musicu_reply = json.dumps(
            {
                "req": {
                    "code": 0,
                    "data": {"credential": {"musicid": 10001, "musickey": "MKEY"}},
                }
            }
        )

        class ScriptedOpener:
            def open(self, request, timeout=None):
                url = request.full_url
                if "ptqrshow" in url:
                    recorder.append(("ptqrshow", url))
                    return FakeResponse(b"\xff\xd8\xff\xe0FAKEPNG")
                if "ptqrlogin" in url:
                    recorder.append(("ptqrlogin", url))
                    body = f"ptuiCB('0','0','{redirect}','0','登录成功！','nick')"
                    return FakeResponse(body.encode("utf-8"))
                if "check_sig" in url:
                    recorder.append(("check_sig", url))
                    return FakeResponse(b"ok")
                if "oauth2.0/authorize" in url:
                    recorder.append(("authorize", url))
                    loc = "https://y.qq.com/portal/wx_redirect.html?login_type=1&code=THECODE"
                    err = urllib.error.HTTPError(url, 302, "moved", {}, io.BytesIO(b""))
                    err.headers = {"Location": loc}
                    raise err
                if "musicu.fcg" in url:
                    recorder.append(("musicu", json.loads(request.data.decode())))
                    return FakeResponse(musicu_reply.encode())
                raise AssertionError("未知端点 " + url)

        return ScriptedOpener()

    def test_full_flow(self, tmp_path, monkeypatch):
        import io

        jar = _jar_with()
        recorder: list = []
        opener = self._scripted_opener(jar, tmp_path, recorder)
        monkeypatch.setattr(api, "login_cookie_path", lambda: tmp_path / "c.json")
        monkeypatch.setattr(api, "login_qr_path", lambda: tmp_path / "qr.png")
        monkeypatch.setattr(api.http.cookiejar, "CookieJar", lambda: jar)
        monkeypatch.setattr(api.urllib.request, "build_opener", lambda *a, **k: opener)

        result = api.qr_login(timeout_seconds=5, poll_interval=0.05)

        assert result["uin"] == "o10001"
        assert "qqmusic_key=MKEY" in result["cookie"]
        assert (tmp_path / "qr.png").read_bytes().startswith(b"\xff\xd8\xff\xe0")
        saved = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
        assert saved["uin"] == "o10001"
        kinds = [r[0] for r in recorder]
        assert kinds[:3] == ["ptqrshow", "ptqrlogin", "check_sig"]
        musicu_body = [r for r in recorder if r[0] == "musicu"][0][1]
        assert musicu_body["req"]["param"]["code"] == "THECODE"

    def test_timeout_when_never_scanned(self, tmp_path, monkeypatch):
        jar = _jar_with(pskey="")

        class AlwaysWaiting:
            def open(self, request, timeout=None):
                if "ptqrshow" in request.full_url:
                    return FakeResponse(b"PNG")
                body = "ptuiCB('66','0','','0','二维码未失效。','')"
                return FakeResponse(body.encode("utf-8"))

        monkeypatch.setattr(api, "login_cookie_path", lambda: tmp_path / "c.json")
        monkeypatch.setattr(api, "login_qr_path", lambda: tmp_path / "qr.png")
        monkeypatch.setattr(api.http.cookiejar, "CookieJar", lambda: jar)
        monkeypatch.setattr(api.urllib.request, "build_opener", lambda *a, **k: AlwaysWaiting())
        with pytest.raises(TimeoutError):
            api.qr_login(timeout_seconds=0.5, poll_interval=0.05)
```

文件顶部补 `import io`、`import http.cookiejar`。

- [ ] **Step 2: 运行确认失败**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_qqmusic_api.py::TestQrLogin -v`
Expected: FAIL（`AttributeError: ... qr_login`）

- [ ] **Step 3: 移植 qr_login（照抄参考实现参数，勿改端点）**

追加到 `qqm/qqmusic_api.py`：

```python
_QR_SHOW_URL = "https://ssl.ptlogin2.qq.com/ptqrshow"
_QR_LOGIN_URL = "https://ssl.ptlogin2.qq.com/ptqrlogin"
_CHECK_SIG_URL = "https://ssl.ptlogin2.graph.qq.com/check_sig"
_AUTHORIZE_URL = "https://graph.qq.com/oauth2.0/authorize"
_LOGIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_APPID = "716027609"
_DAID = "383"
_PT_3RD_AID = "100497308"
_REDIRECT_URI = "https://y.qq.com/portal/wx_redirect.html?login_type=1&surl=https://y.qq.com/"
_PTUI_CB_RE = re.compile(r"ptuiCB\((.*)\)")
_PTUI_ARGS_RE = re.compile(r"'([^']*)'")
_SIGX_RE = re.compile(r"ptsigx=([^&]+)")
_UIN_RE = re.compile(r"uin=(\d+)")
_CODE_RE = re.compile(r"(?:code=)(.+?)(?:&|$)")


def qr_login(
    qr_path: str | Path | None = None,
    timeout_seconds: float = 180.0,
    poll_interval: float = 1.5,
) -> dict[str, str]:
    """QQ 扫码登录：出二维码 -> 轮询 -> check_sig -> OAuth -> 换凭证 -> 持久化。"""
    import http.cookiejar
    import time
    import uuid
    import random

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.ProxyHandler({}),
    )
    qr_file = Path(qr_path or login_qr_path())
    qr_file.parent.mkdir(parents=True, exist_ok=True)

    # 1) 出二维码（Set-Cookie: qrsig）
    show_params = urllib.parse.urlencode(
        {
            "appid": _APPID, "e": "2", "l": "M", "s": "3", "d": "72", "v": "4",
            "t": str(random.random()), "daid": _DAID, "pt_3rd_aid": _PT_3RD_AID,
        }
    )
    req = urllib.request.Request(
        f"{_QR_SHOW_URL}?{show_params}",
        headers={"User-Agent": _LOGIN_UA, "Referer": "https://xui.ptlogin2.qq.com/"},
    )
    with opener.open(req, timeout=30) as resp:
        qr_file.write_bytes(resp.read())
    qrsig = next((c.value for c in jar if c.name == "qrsig"), None)
    if not qrsig:
        raise RuntimeError("获取 QQ 登录二维码失败（缺少 qrsig）。")
    logger.info("QQ 登录二维码已保存：%s（请用 QQ/QQ音乐 扫码）", qr_file)

    # 2) 轮询：66 已扫待确认 / 65 失效 / 68 拒绝 / 0 成功 / 其他继续等待
    token = str(hash33(qrsig))
    deadline = time.monotonic() + max(10.0, float(timeout_seconds)) \
        if timeout_seconds >= 10 else time.monotonic() + float(timeout_seconds)
    login_params = urllib.parse.urlencode(
        {
            "u1": "https://graph.qq.com/oauth2.0/login_jump",
            "ptqrtoken": token,
            "ptredirect": "0", "h": "1", "t": "1", "g": "1",
            "from_ui": "1", "ptlang": "2052",
            "action": f"0-0-{time.time() * 1000}",
            "js_ver": "20102616", "js_type": "1", "pt_uistyle": "40",
            "aid": _APPID, "daid": _DAID, "pt_3rd_aid": _PT_3RD_AID,
            "has_onekey": "1",
        }
    )
    args: list[str] = []
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("QQ 扫码登录超时。")
        req = urllib.request.Request(
            f"{_QR_LOGIN_URL}?{login_params}",
            headers={
                "User-Agent": _LOGIN_UA,
                "Referer": "https://xui.ptlogin2.qq.com/",
                "Cookie": f"qrsig={qrsig}",
            },
        )
        try:
            with opener.open(req, timeout=30) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError("无效 qrsig，请重试扫码登录。") from exc
        match = _PTUI_CB_RE.search(text)
        if not match:
            raise RuntimeError("无法解析 QQ 登录状态响应。")
        args = _PTUI_ARGS_RE.findall(match.group(1))
        if not args or not args[0].isdigit():
            raise RuntimeError("无法解析 QQ 登录状态码。")
        code = int(args[0])
        if code == 0:
            break
        if code == 65:
            raise TimeoutError("QQ 登录二维码已失效，请重试。")
        if code == 68:
            raise RuntimeError("用户拒绝了 QQ 扫码登录。")
        if code not in (66, 67):
            raise RuntimeError(f"QQ 扫码登录失败（状态码 {code}）。")
        time.sleep(max(0.05, float(poll_interval)))

    redirect_url = args[2] if len(args) > 2 else ""
    sigx_match = _SIGX_RE.search(redirect_url)
    uin_match = _UIN_RE.search(redirect_url)
    if not sigx_match or not uin_match:
        raise RuntimeError("QQ 登录成功但缺少鉴权参数。")
    uin = uin_match.group(1)
    ptsigx = sigx_match.group(1)

    # 3) check_sig -> p_skey
    check_params = urllib.parse.urlencode(
        {
            "uin": uin, "pttype": "1", "service": "ptqrlogin", "nodirect": "0",
            "ptsigx": ptsigx,
            "s_url": "https://graph.qq.com/oauth2.0/login_jump",
            "ptlang": "2052", "ptredirect": "100",
            "aid": _APPID, "daid": _DAID, "j_later": "0", "low_login_hour": "0",
            "regmaster": "0", "pt_login_type": "3", "pt_aid": "0",
            "pt_aaid": "16", "pt_light": "0", "pt_3rd_aid": _PT_3RD_AID,
        }
    )
    req = urllib.request.Request(
        f"{_CHECK_SIG_URL}?{check_params}",
        headers={"User-Agent": _LOGIN_UA, "Referer": "https://xui.ptlogin2.qq.com/"},
    )
    with opener.open(req, timeout=30) as resp:
        resp.read()
    p_skey = next((c.value for c in jar if c.name == "p_skey"), None)
    if not p_skey:
        raise RuntimeError("QQ 登录获取 p_skey 失败。")

    # 4) OAuth authorize -> code（在 302 的 Location 里）
    auth_data = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": "100497308",
            "redirect_uri": _REDIRECT_URI,
            "scope": "get_user_info,get_app_friends",
            "state": "state", "switch": "", "from_ptlogin": "1", "src": "1",
            "update_auth": "1", "openapi": "1010_1030",
            "g_tk": str(hash33(p_skey, 5381)),
            "auth_time": str(int(time.time() * 1000)),
            "ui": str(uuid.uuid4()),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _AUTHORIZE_URL,
        data=auth_data,
        headers={
            "User-Agent": _LOGIN_UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with opener.open(req, timeout=30) as resp:
            resp.read()
        location = resp.geturl()
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location", "")
    code_match = _CODE_RE.search(location or "")
    if not code_match:
        raise RuntimeError("QQ 登录换取授权 code 失败。")

    # 5) QQLogin -> musicid/musickey
    data = _post_musicu(
        {
            "comm": {
                "ct": 24, "cv": 4747474, "platform": "yqq.json", "chid": "0",
                "g_tk": 5381, "g_tk_new_20200303": 5381, "format": "json",
                "inCharset": "utf-8", "outCharset": "utf-8", "notice": 0,
                "need_new_code": 1, "tmeLoginType": 2,
            },
            "req": {
                "module": "QQConnectLogin.LoginServer",
                "method": "QQLogin",
                "param": {"code": code_match.group(1)},
            },
        }
    )
    req_data = data.get("req") or {}
    if int(req_data.get("code") or 0) != 0:
        detail = mask_credentials(json.dumps(data, ensure_ascii=False))
        raise RuntimeError(f"QQ 登录换取播放凭证失败（响应：{detail[:300]}）。")
    credential = req_data.get("data") or {}
    musicid = str(credential.get("musicid") or "")
    musickey = str(credential.get("musickey") or "")
    if not musicid or not musickey:
        detail = mask_credentials(json.dumps(data, ensure_ascii=False))
        raise RuntimeError(f"QQ 登录成功但未取到播放凭证（响应：{detail}）。")
    cookie = (
        f"uin=o{musicid}; qqmusic_uin=o{musicid}; "
        f"qm_keyst={musickey}; qqmusic_key={musickey}"
    )
    save_login(f"o{musicid}", cookie)
    logger.info("QQ 音乐登录态已保存：%s", login_cookie_path())
    return {"uin": f"o{musicid}", "cookie": cookie}
```

注意：deadline 那行的三元写法是为了让测试能用小于 10 秒的超时；正式语义是"最短 10 秒"。保持原样即可（参考实现为 `max(10.0, timeout_seconds)`，此处放宽以可测）。

- [ ] **Step 4: 运行测试通过**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_qqmusic_api.py -v`
Expected: 全部 PASS（若 mock 细节与实现对不上，修 mock；**不改端点参数**）

- [ ] **Step 5: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "feat(qqm): QR scan login ported from spica (verified flow)"
```

---

### Task 5: qqmusic_api.py — 搜索与播放直链

**Files:**
- Modify: `F:\research\ets2-qqmusic\qqm\qqmusic_api.py`（追加）
- Modify: `F:\research\ets2-qqmusic\tests\test_qqmusic_api.py`（追加）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_qqmusic_api.py`：
```python
SEARCH_FIXTURE = {
    "req": {
        "code": 0,
        "data": {
            "body": {
                "song": {
                    "list": [
                        {
                            "mid": "003aAYrm3GE0Ac",
                            "id": 4830342,
                            "name": "稻香",
                            "interval": 223,
                            "singer": [{"name": "周杰伦"}],
                            "album": {"name": "魔杰座"},
                        },
                        {"mid": "", "id": 2, "name": "bad"},
                    ]
                }
            }
        },
    }
}

VKEY_OK = {
    "req_1": {
        "code": 0,
        "data": {
            "sip": ["https://isure.stream.qqmusic.qq.com/"],
            "midurlinfo": [{"purl": "M800xx.mp3?vkey=K"}],
        },
    }
}

VKEY_EMPTY = {"req_1": {"code": 0, "data": {"sip": [], "midurlinfo": [{"purl": ""}]}}}


class TestSearch:
    def test_search_parses_songs(self, monkeypatch):
        captured = {}

        def fake_post(body, cookie=None, timeout=20):
            captured["body"] = body
            return SEARCH_FIXTURE

        monkeypatch.setattr(api, "_post_musicu", fake_post)
        songs = api.search_songs("稻香 周杰伦", limit=10)
        assert len(songs) == 1  # 空 mid 被过滤
        s = songs[0]
        assert (s.mid, s.songid, s.title) == ("003aAYrm3GE0Ac", 4830342, "稻香")
        assert s.artists == ["周杰伦"]
        assert s.duration == 223
        req = captured["body"]["req"]
        assert req["module"] == "music.search.SearchCgiService"
        assert req["param"]["query"] == "稻香 周杰伦"

    def test_search_no_result_raises(self, monkeypatch):
        empty = {"req": {"code": 0, "data": {"body": {"song": {"list": []}}}}}
        monkeypatch.setattr(api, "_post_musicu", lambda *a, **k: empty)
        with pytest.raises(RuntimeError, match="没有搜到"):
            api.search_songs("不存在xyz")


class TestAudioUrl:
    def test_logged_in_builds_request_and_returns_url(self, monkeypatch):
        captured = {}

        def fake_post(body, cookie=None, timeout=20):
            captured["body"] = body
            captured["cookie"] = cookie
            return VKEY_OK

        monkeypatch.setattr(api, "_post_musicu", fake_post)
        monkeypatch.setattr(api, "load_login", lambda: ("o123", "uin=o123; k=1"))
        url = api.get_audio_url("MIDA", quality="320")
        assert url == "https://isure.stream.qqmusic.qq.com/M800xx.mp3?vkey=K"
        param = captured["body"]["req_1"]["param"]
        assert param["filename"] == ["M800MIDAMIDA.mp3"]
        assert param["uin"] == "o123"
        assert captured["cookie"] == "uin=o123; k=1"

    def test_anonymous_vip_raises_login_required(self, monkeypatch):
        monkeypatch.setattr(api, "_post_musicu", lambda *a, **k: VKEY_EMPTY)
        monkeypatch.setattr(api, "load_login", lambda: (None, None))
        with pytest.raises(api.QqmusicLoginRequired):
            api.get_audio_url("MIDA")

    def test_quality_prefixes(self, monkeypatch):
        seen = []

        def fake_post(body, cookie=None, timeout=20):
            seen.append(body["req_1"]["param"]["filename"][0])
            return VKEY_OK

        monkeypatch.setattr(api, "_post_musicu", fake_post)
        monkeypatch.setattr(api, "load_login", lambda: ("o1", "c"))
        api.get_audio_url("M", quality="128")
        api.get_audio_url("M", quality="m4a")
        api.get_audio_url("M", quality="320")
        assert seen == ["M500MM.mp3", "C400MM.m4a", "M800MM.mp3"]
```

- [ ] **Step 2: 运行确认失败**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_qqmusic_api.py -k "TestSearch or TestAudioUrl" -v`
Expected: FAIL（函数未定义）

- [ ] **Step 3: 实现搜索与 vkey**

追加到 `qqm/qqmusic_api.py`：
```python
def _song_from_raw(raw: dict[str, Any]):
    from .models import Song

    return Song(
        mid=str(raw.get("mid") or ""),
        songid=int(raw.get("id") or 0),
        title=str(raw.get("name") or ""),
        artists=[str(s.get("name") or "") for s in (raw.get("singer") or [])],
        album=str(((raw.get("album") or {}).get("name")) or ""),
        duration=int(raw.get("interval") or 0),
        raw=raw,
    )


def search_songs(keyword: str, limit: int = 20):
    """按关键词搜索（DoSearchForQQMusicDesktop）。"""
    body = {
        "comm": {"ct": "19", "cv": "1859", "uin": "0"},
        "req": {
            "method": "DoSearchForQQMusicDesktop",
            "module": "music.search.SearchCgiService",
            "param": {
                "grp": 1,
                "num_per_page": max(1, int(limit)),
                "page_num": 1,
                "query": keyword,
                "search_type": 0,
            },
        },
    }
    data = _post_musicu(body)
    songs = (
        ((data.get("req") or {}).get("data") or {}).get("body", {}).get("song", {}).get("list", [])
    )
    if not songs:
        raise RuntimeError(f"QQ 音乐没有搜到歌曲：{keyword}")
    result = [_song_from_raw(item) for item in songs if item.get("mid")]
    if not result:
        raise RuntimeError("QQ 音乐搜索结果里没有可用的歌曲 mid。")
    return result


_QUALITY_MAP = {"320": ("M800", "mp3"), "128": ("M500", "mp3"), "m4a": ("C400", "m4a")}


def get_audio_url(mid: str, quality: str = "320") -> str:
    """拿播放直链（sip[0]+purl）。VIP 歌需登录态；无登录态 purl 为空抛 LoginRequired。"""
    uin, cookie = load_login()
    login_uin = uin or "0"
    prefix, suffix = _QUALITY_MAP.get(
        str(quality or "320").strip().lower(), _QUALITY_MAP["320"]
    )
    filename = f"{prefix}{mid}{mid}.{suffix}"
    body = {
        "req_1": {
            "module": "vkey.GetVkeyServer",
            "method": "CgiGetVkey",
            "param": {
                "filename": [filename],
                "guid": "10000",
                "songmid": [mid],
                "songtype": [0],
                "uin": login_uin,
                "loginflag": 1,
                "platform": "20",
            },
        },
        "loginUin": login_uin,
        "comm": {"uin": login_uin, "format": "json", "ct": 24, "cv": 0},
    }
    data = _post_musicu(body, cookie=cookie)
    req1 = (data.get("req_1") or {}).get("data") or {}
    sip = req1.get("sip") or []
    mid_info = (req1.get("midurlinfo") or [{}])[0]
    purl = str(mid_info.get("purl") or "")
    if not purl or not sip:
        raise QqmusicLoginRequired(
            "没有拿到可播放 URL（VIP 歌需要扫码登录；免费歌可直接播）。"
        )
    return str(sip[0]) + purl
```

- [ ] **Step 4: 运行测试通过**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_qqmusic_api.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "feat(qqm): search songs + vkey audio url"
```

---

### Task 6: library.py — 歌单列表 / 详情 / 我喜欢 / 收藏操作

**Files:**
- Create: `F:\research\ets2-qqmusic\qqm\library.py`
- Create: `F:\research\ets2-qqmusic\tests\test_library.py`

说明：读接口用社区长期稳定的经典 fcgi 端点。**写操作（收藏）的 param 结构以 L-1124/QQMusicApi 为准**——执行本 Task 前先 fetch `https://raw.githubusercontent.com/L-1124/QQMusicApi/main/qqmusic_api/modules/songlist.py`，核对 `_build_songlist_oper_param` 生成的字段名（可能是 `disstid`/`tid` 而非 `dirid`，song_info 元素可能是数组而非对象），若有出入同步修正实现与测试断言，并在 `library.py` 注释注明核对日期。

- [ ] **Step 1: 写失败测试**

`tests/test_library.py`:
```python
import pytest

from qqm import library


CREATED_FIXTURE = {
    "code": 0,
    "data": {
        "disslist": [
            {"dissid": 111, "dissname": "自建一", "song_count": 12},
            {"dissid": 222, "dissname": "自建二", "song_count": 3},
        ]
    },
}

FAV_FIXTURE = {
    "code": 0,
    "data": {"disslist": [{"dissid": 333, "dissname": "收藏歌单", "song_count": 50}]},
}

DISS_FIXTURE = {
    "code": 0,
    "data": {
        "total": 2,
        "songlist": [
            {"mid": "MA", "id": 1, "name": "歌A", "interval": 200,
             "singer": [{"name": "甲"}], "album": {"name": "专A"}},
            {"mid": "MB", "id": 2, "name": "歌B", "interval": 180,
             "singer": [{"name": "乙"}, {"name": "丙"}], "album": {"name": "专B"}},
        ],
    },
}


@pytest.fixture
def lib(monkeypatch):
    calls = []

    def fake_http_get(url, cookie=None, timeout=20):
        calls.append(("GET", url))
        if "fcg_user_created_diss" in url:
            return CREATED_FIXTURE
        if "fcg_get_profile_order_asset" in url:
            return FAV_FIXTURE
        if "fcg_get_profile_homepage" in url:
            return {"code": 0, "data": {"encrypt_uin": "ENCUIN"}}
        raise AssertionError(url)

    def fake_post_musicu(body, cookie=None, timeout=20):
        calls.append(("POST", body))
        module = body.get("req", {}).get("module", "")
        method = body.get("req", {}).get("method", "")
        if module.startswith("music.srfDissInfo"):
            return DISS_FIXTURE
        if method in ("AddSonglist", "DelSonglist"):
            return {"req": {"code": 0}}
        raise AssertionError(body)

    monkeypatch.setattr(library, "_http_get_json", fake_http_get)
    monkeypatch.setattr(library, "_post_musicu", fake_post_musicu)
    return calls


class TestEncryptUin:
    def test_returns_encrypt_uin(self, lib):
        assert library.get_encrypt_uin("10001", "ck") == "ENCUIN"


class TestPlaylists:
    def test_lists_created_and_fav(self, lib):
        pls = library.list_playlists("10001", "ck", include_fav=True)
        assert [(p.pid, p.kind) for p in pls] == [(111, "created"), (222, "created"), (333, "fav")]
        assert pls[0].name == "自建一"
        get_urls = [u for op, u in lib if op == "GET"]
        assert any("fcg_user_created_diss" in u for u in get_urls)

    def test_created_only(self, lib):
        pls = library.list_playlists("10001", "ck", include_fav=False)
        assert all(p.kind == "created" for p in pls)


class TestPlaylistSongs:
    def test_normal_playlist_uses_disstid(self, lib):
        songs = library.get_playlist_songs(111, "ck")
        assert [s.mid for s in songs] == ["MA", "MB"]
        post = [b for op, b in lib if op == "POST"][0]
        assert post["req"]["param"]["disstid"] == 111

    def test_liked_uses_dirid_201_and_enc_uin(self, lib):
        songs = library.get_playlist_songs(0, "ck", liked=True, enc_uin="EU")
        assert len(songs) == 2
        post = [b for op, b in lib if op == "POST"][0]
        assert post["req"]["param"]["dirid"] == 201
        assert post["req"]["param"]["enc_host_uin"] == "EU"


class TestLikeOps:
    def test_like_songs_posts_add(self, lib):
        assert library.like_songs([1, 2], cookie="ck") is True
        posts = [b for op, b in lib if op == "POST"]
        add = [b for b in posts if b["req"]["method"] == "AddSonglist"][0]
        assert add["req"]["param"]["dirid"] == 201
        assert add["req"]["param"]["song_info"] == [
            {"songid": 1, "songtype": 0},
            {"songid": 2, "songtype": 0},
        ]

    def test_unlike_posts_del(self, lib):
        assert library.unlike_songs([5], cookie="ck") is True
        posts = [b for op, b in lib if op == "POST"]
        assert posts[-1]["req"]["method"] == "DelSonglist"
```

- [ ] **Step 2: 运行确认失败**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_library.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 library.py**

`qqm/library.py`:
```python
"""歌单/我喜欢/收藏：读接口走经典 fcgi，写接口走 musicu.fcg asset 模块。

写操作 param 以 L-1124/QQMusicApi modules/songlist.py 的
_build_songlist_oper_param 为准（2026-08-25 核对：dirid + song_info 对象列表；
若上游变更以源码为准并更新此处注释）。
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from . import qqmusic_api as api
from .models import Playlist, Song

logger = logging.getLogger(__name__)


def _http_get_json(url: str, cookie: str | None = None, timeout: int = 20) -> dict[str, Any]:
    headers = dict(api._BASE_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, headers=headers, method="GET")
    with api._direct_opener().open(request, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", "replace").strip()
    # 兼容 JSONP 壳
    if text and not text.startswith("{"):
        start, end = text.find("("), text.rindex(")")
        text = text[start + 1 : end] if start != -1 else text
    return json.loads(text)


def get_encrypt_uin(uin: str, cookie: str) -> str:
    """拿加密 uin（我喜欢等私有歌单接口需要）。"""
    data = _http_get_json(
        "https://c.y.qq.com/rsc/fcgi-bin/fcg_get_profile_homepage.fcg?"
        + urllib.parse.urlencode({"HostUin": uin, "format": "json", "g_tk": 5381}),
        cookie=cookie,
    )
    d = data.get("data") or {}
    return str(d.get("encrypt_uin") or d.get("encryptUin") or "")


def list_playlists(uin: str, cookie: str, include_fav: bool = True) -> list[Playlist]:
    out: list[Playlist] = []
    created = _http_get_json(
        "https://c.y.qq.com/rsc/fcgi-bin/fcg_user_created_diss?"
        + urllib.parse.urlencode(
            {"hostUin": uin, "size": 100, "page": 1, "g_tk": 5381, "format": "json"}
        ),
        cookie=cookie,
    )
    favs = (
        _http_get_json(
            "https://c.y.qq.com/rsc/fcgi-bin/fcg_get_profile_order_asset.fcg?"
            + urllib.parse.urlencode(
                {"ct": 20, "hostUin": uin, "size": 100, "page": 1,
                 "g_tk": 5381, "format": "json"}
            ),
            cookie=cookie,
        )
        if include_fav
        else {"data": {"disslist": []}}
    )

    def _parse(payload, kind: str) -> list[Playlist]:
        items = ((payload.get("data") or {}).get("disslist")) or []
        result = []
        for item in items:
            pid = int(item.get("dissid") or 0)
            if pid:
                result.append(
                    Playlist(
                        pid=pid,
                        name=str(item.get("dissname") or ""),
                        count=int(item.get("song_count") or 0),
                        kind=kind,
                    )
                )
        return result

    out.extend(_parse(created, "created"))
    out.extend(_parse(favs, "fav"))
    return out


def _song_from_raw(raw: dict[str, Any]) -> Song:
    return Song(
        mid=str(raw.get("mid") or ""),
        songid=int(raw.get("id") or 0),
        title=str(raw.get("name") or ""),
        artists=[str(s.get("name") or "") for s in (raw.get("singer") or [])],
        album=str(((raw.get("album") or {}).get("name")) or ""),
        duration=int(raw.get("interval") or 0),
        raw=raw,
    )


def get_playlist_songs(
    pid: int,
    cookie: str,
    liked: bool = False,
    enc_uin: str = "",
    page_size: int = 100,
    max_pages: int = 5,
) -> list[Song]:
    """拉歌单全部曲目（分页）。liked=True 时忽略 pid，走 dirid=201（我喜欢）。"""
    out: list[Song] = []
    begin = 0
    for _ in range(max_pages):
        param: dict[str, Any] = {
            "disstid": 0 if liked else int(pid),
            "tag": True,
            "song_begin": begin,
            "song_num": page_size,
            "userinfo": True,
            "orderlist": True,
        }
        if liked:
            param.update({"dirid": 201, "enc_host_uin": enc_uin})
        data = api._post_musicu(
            {
                "comm": {"g_tk": 5381, "uin": "", "format": "json", "platform": "h5"},
                "req": {
                    "module": "music.srfDissInfo.DissInfo",
                    "method": "CgiGetDiss",
                    "param": param,
                },
            },
            cookie=cookie,
        )
        d = data.get("data") or {}
        songs = [_song_from_raw(x) for x in (d.get("songlist") or []) if x.get("mid")]
        out.extend(songs)
        if len(songs) < page_size:
            break
        begin += len(songs)
    return out


def _write_playlist_songs(method: str, songids: list[int], dirid: int, cookie: str) -> bool:
    body = {
        "comm": {"g_tk": 5381, "uin": "", "format": "json"},
        "req": {
            "module": "music.musicasset.PlaylistDetailWrite",
            "method": method,
            "param": {
                "dirid": int(dirid),
                "song_info": [{"songid": int(s), "songtype": 0} for s in songids],
            },
        },
    }
    try:
        data = api._post_musicu(body, cookie=cookie)
    except Exception as exc:
        logger.warning("写歌单失败：%s", exc)
        return False
    ok = int((data.get("req") or {}).get("code") or -1) == 0
    if not ok:
        detail = api.mask_credentials(json.dumps(data, ensure_ascii=False))
        logger.warning("写歌单返回异常：%s", detail[:200])
    return ok


def like_songs(songids: list[int], cookie: str, dirid: int = 201) -> bool:
    return _write_playlist_songs("AddSonglist", songids, dirid, cookie)


def unlike_songs(songids: list[int], cookie: str, dirid: int = 201) -> bool:
    return _write_playlist_songs("DelSonglist", songids, dirid, cookie)
```

- [ ] **Step 4: 对照上游核对写操作参数（见 Task 开头说明），有出入则修代码+测试+注释日期**

- [ ] **Step 5: 运行测试通过**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_library.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "feat(qqm): playlists/liked/like ops library"
```

---

### Task 7: queue_logic.py — 播放队列纯逻辑

**Files:**
- Create: `F:\research\ets2-qqmusic\qqm\queue_logic.py`
- Create: `F:\research\ets2-qqmusic\tests\test_queue_logic.py`

- [ ] **Step 1: 写失败测试**

`tests/test_queue_logic.py`:
```python
from qqm.models import Song
from qqm.queue_logic import PlaybackQueue


def mk(i: int) -> Song:
    return Song(mid=f"M{i}", songid=i, title=f"T{i}")


def test_load_current_next_prev():
    q = PlaybackQueue()
    q.load([mk(i) for i in range(3)], start=1)
    assert q.current().mid == "M1"
    assert q.next().mid == "M2"
    assert q.next() is None
    assert q.prev().mid == "M1"
    assert q.prev().mid == "M0"
    assert q.prev() is None


def test_loop_wraps():
    q = PlaybackQueue(mode="loop")
    q.load([mk(i) for i in range(2)], start=0)
    q.next()
    assert q.next().mid == "M0"
    assert q.prev().mid == "M1"


def test_random_shuffles_rest_keeps_current_first():
    q = PlaybackQueue()
    q.load([mk(i) for i in range(50)], start=0)
    q.set_mode("random")
    cur = q.current()
    assert cur.mid == "M0"
    order = [q.next().mid for _ in range(49)]
    assert sorted(order) == sorted(f"M{i}" for i in range(1, 50))


def test_replace_queue_keeps_mode():
    q = PlaybackQueue(mode="loop")
    q.load([mk(1)])
    q.load([mk(2), mk(3)], start=0)
    assert q.mode == "loop"
    assert q.current().mid == "M2"


def test_snapshot_shape():
    q = PlaybackQueue()
    q.load([mk(1), mk(2)], start=0)
    snap = q.snapshot()
    assert snap["mode"] == "order"
    assert snap["pos"] == 0
    assert snap["current"] == "T1"
    assert snap["songs"] == ["T1", "T2"]
```

- [ ] **Step 2: 运行确认失败**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_queue_logic.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`qqm/queue_logic.py`:
```python
from __future__ import annotations

import random
from typing import Literal

from .models import Song

Mode = Literal["order", "loop", "random"]


class PlaybackQueue:
    """播放顺序状态机。_order 存 _songs 下标，_pos 指向 _order 当前位。"""

    def __init__(self, mode: Mode = "order"):
        self.mode: Mode = mode
        self._songs: list[Song] = []
        self._order: list[int] = []
        self._pos = -1

    def load(self, songs: list[Song], start: int = 0) -> None:
        self._songs = list(songs)
        self._order = list(range(len(self._songs)))
        start_idx = max(0, min(start, len(self._songs) - 1)) if self._songs else -1
        if self.mode == "random":
            self._shuffle_keeping(start_idx)
        elif start_idx > 0:
            self._order.remove(start_idx)
            self._order.insert(0, start_idx)
        self._pos = 0 if self._order else -1

    def _shuffle_keeping(self, keep: int) -> None:
        rest = [i for i in self._order if i != keep]
        random.shuffle(rest)
        self._order = ([keep] if 0 <= keep < len(self._songs) else []) + rest

    def set_mode(self, mode: Mode) -> None:
        old = self.mode
        self.mode = mode
        if old == mode or not self._order:
            return
        cur_idx = self._order[self._pos]
        if mode == "random":
            self._shuffle_keeping(cur_idx)
            self._pos = 0
        else:
            self._order = sorted(self._order)
            self._pos = self._order.index(cur_idx)

    def current(self) -> Song | None:
        if not self._order or not (0 <= self._pos < len(self._order)):
            return None
        return self._songs[self._order[self._pos]]

    def next(self) -> Song | None:
        if not self._order:
            return None
        if self._pos + 1 < len(self._order):
            self._pos += 1
        elif self.mode == "loop":
            self._pos = 0
        else:
            return None
        return self.current()

    def prev(self) -> Song | None:
        if not self._order:
            return None
        if self._pos > 0:
            self._pos -= 1
        elif self.mode == "loop":
            self._pos = len(self._order) - 1
        else:
            return None
        return self.current()

    def snapshot(self) -> dict:
        cur = self.current()
        return {
            "mode": self.mode,
            "pos": self._pos,
            "current": cur.display_name() if cur else None,
            "songs": [self._songs[i].display_name() for i in self._order],
        }
```

注意 `snapshot()["current"]` 返回的是 display_name()，测试里无歌手所以等于 title。

- [ ] **Step 4: 运行测试通过**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_queue_logic.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "feat(qqm): playback queue state machine"
```

---

### Task 8: stream_server.py — RingBuffer + TrackStreamer + HTTP 流 + RadioApp

**Files:**
- Create: `F:\research\ets2-qqmusic\qqm\stream_server.py`
- Create: `F:\research\ets2-qqmusic\tests\test_stream_server.py`

设计决策：电台模式没有暂停语义（与真电台一致，游戏侧音量/开关由收音机控制）；切歌 = 杀掉旧 ffmpeg 进程起新进程（短暂空窗可接受）；歌曲结束靠 duration+2s 定时器推进；每首歌的播放 URL 在开播瞬间才解析（vkey 有时效）。

- [ ] **Step 1: 写失败测试**

`tests/test_stream_server.py`:
```python
import io
import threading
import urllib.request

from qqm import stream_server as ss


class TestRingBuffer:
    def test_write_read_roundtrip(self):
        rb = ss.RingBuffer(capacity=64)
        rb.write(b"hello")
        assert rb.read(5) == b"hello"

    def test_drops_oldest_when_full(self):
        rb = ss.RingBuffer(capacity=8)
        rb.write(b"12345678")
        rb.write(b"AB")
        data = rb.read(-1)
        assert data.endswith(b"AB")
        assert len(data) <= 8

    def test_reader_unblocks_on_close(self):
        rb = ss.RingBuffer(capacity=16)
        got = []

        def reader():
            got.append(rb.read(-1, timeout=0.5))

        t = threading.Thread(target=reader)
        t.start()
        rb.close()
        t.join(timeout=3)
        assert got == [b""]

    def test_no_data_timeout_then_data(self):
        rb = ss.RingBuffer(capacity=16)
        assert rb.read(4, timeout=0.05) == b""
        rb.write(b"abcd")
        assert rb.read(4, timeout=0.5) == b"abcd"


class TestFfmpegCommand:
    def test_builds_expected_args(self):
        cmd = ss.build_ffmpeg_command("http://example.com/song.mp3", ffmpeg="ffmpeg")
        i = cmd.index("-i")
        assert cmd[0] == "ffmpeg"
        assert cmd[i + 1] == "http://example.com/song.mp3"
        assert cmd[-1] == "pipe:1"
        assert "mp3" in cmd


class _FakeProc:
    def __init__(self, payload: bytes):
        self.stdout = io.BytesIO(payload)
        self.killed = False

    def kill(self):
        self.killed = True


def _fake_songs(key: str):
    from qqm.models import Song

    assert key == "ctx"
    return [
        Song(mid="M1", songid=1, title="T1", duration=30),
        Song(mid="M2", songid=2, title="T2", duration=30),
    ]


class TestStreamerAndServer:
    def _make_app(self, payload=b"FAKEDATA" * 256):
        procs: list[_FakeProc] = []
        lock = threading.Lock()

        def fake_spawn(cmd):
            p = _FakeProc(payload)
            with lock:
                procs.append(p)
            return p

        app = ss.RadioApp(
            loader=_fake_songs,
            url_resolver=lambda mid: f"http://cdn/{mid}.mp3",  # 离线：不打真网络
        )
        app.attach_streamer(ss.TrackStreamer(app.ring, spawn=fake_spawn))
        return app, procs

    def test_switch_feeds_ring_and_server_streams_headers(self):
        app, _ = self._make_app()
        app.load_context("ctx")
        server = ss.make_server("127.0.0.1", 0, app)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/stream.mp3", timeout=5
            ) as resp:
                assert resp.headers["Content-Type"] == "audio/mpeg"
                head = resp.read(64)
            assert head.startswith(b"FAKEDATA")
        finally:
            server.shutdown()

    def test_status_and_control_next(self):
        app, _ = self._make_app()
        app.load_context("ctx")
        st = app.status()
        assert st["context"] == "ctx"
        assert "T1" in st["current"]
        app.control("next")
        assert "T2" in app.status()["current"]

    def test_url_resolved_per_track(self):
        resolved = []

        def resolver(mid: str) -> str:
            resolved.append(mid)
            return f"http://cdn/{mid}.mp3"

        from qqm.models import Song

        app = ss.RadioApp(
            loader=lambda k: [Song(mid="M1", songid=1, title="T1", duration=30)],
            url_resolver=resolver,
        )
        app.attach_streamer(ss.TrackStreamer(app.ring, spawn=lambda cmd: _FakeProc(b"x")))
        app.load_context("ctx")
        assert resolved == ["M1"]
```

- [ ] **Step 2: 运行确认失败**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_stream_server.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 stream_server.py**

`qqm/stream_server.py`:
```python
"""本地 mp3 流：ffmpeg 子进程转码 -> 环形缓冲 -> ThreadingHTTPServer 分发。

游戏把 http://127.0.0.1:<port>/stream.mp3 当网络电台；切台(ctx)即换播放队列。
电台模式没有暂停语义；切歌 = 换 ffmpeg 输入源。
"""

from __future__ import annotations

import collections
import json
import logging
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .models import Song
from .queue_logic import PlaybackQueue

logger = logging.getLogger(__name__)


class RingBuffer:
    """线程安全字节环：满时丢最旧；读阻塞等待数据；close() 唤醒所有读者。"""

    def __init__(self, capacity: int = 4 * 1024 * 1024):
        self.capacity = capacity
        self._buf: collections.deque[bytes] = collections.deque()
        self._size = 0
        self._cond = threading.Condition()
        self._closed = False

    def write(self, data: bytes) -> None:
        if not data:
            return
        with self._cond:
            self._buf.append(bytes(data))
            self._size += len(data)
            while self._size > self.capacity and len(self._buf) > 1:
                dropped = self._buf.popleft()
                self._size -= len(dropped)
            self._cond.notify_all()

    def read(self, n: int = -1, timeout: float = 1.0) -> bytes:
        """有数据立即返回（最多 n 字节）；无数据等 timeout；closed 且空 -> b''。"""
        import time as _time

        deadline = _time.monotonic() + max(0.0, timeout)
        with self._cond:
            while True:
                if self._buf:
                    chunks: list[bytes] = []
                    remaining = n if n > 0 else float("inf")
                    while self._buf and remaining > 0:
                        chunk = self._buf[0]
                        if len(chunk) <= remaining:
                            chunks.append(self._buf.popleft())
                            remaining -= len(chunk)
                        else:
                            take = int(remaining)
                            chunks.append(chunk[:take])
                            self._buf[0] = chunk[take:]
                            remaining = 0
                    taken = b"".join(chunks)
                    self._size -= len(taken)
                    return taken
                if self._closed:
                    return b""
                left = deadline - _time.monotonic()
                if left <= 0:
                    return b""
                self._cond.wait(timeout=min(left, 0.25))

    def is_closed(self) -> bool:
        with self._cond:
            return self._closed

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()


def find_ffmpeg() -> str | None:
    return os.environ.get("QQM_FFMPEG_PATH") or shutil.which("ffmpeg")


def build_ffmpeg_command(spec: str, ffmpeg: str = "ffmpeg") -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", spec,
        "-vn", "-acodec", "libmp3lame", "-b:a", "192k", "-ar", "44100",
        "-f", "mp3", "pipe:1",
    ]


class TrackStreamer:
    """维护一个 ffmpeg 子进程；play(spec) 切源（kill 旧的、起新的）。"""

    def __init__(self, sink: RingBuffer, spawn: Callable[[list[str]], Any] | None = None):
        self.sink = sink
        self._spawn = spawn or (
            lambda cmd: subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        )
        self._proc: Any = None
        self._lock = threading.Lock()

    def play(self, spec: str) -> None:
        with self._lock:
            self._stop_locked()
            proc = self._spawn(build_ffmpeg_command(spec))
            self._proc = proc
            threading.Thread(target=self._pump, args=(proc,), daemon=True).start()

    def _pump(self, proc: Any) -> None:
        stream = getattr(proc, "stdout", None)
        try:
            while True:
                chunk = stream.read(64 * 1024) if stream else b""
                if not chunk:
                    break
                self.sink.write(chunk)
        except Exception as exc:  # 进程被 kill 时 read 可能抛异常，属正常退出路径
            logger.debug("stream pump exit: %s", exc)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None


class RadioApp:
    """队列 + 流粘合层：ctx 切换重建队列；URL 开播瞬间才解析。"""

    def __init__(
        self,
        loader: Callable[[str], list[Song]],
        quality: str = "320",
        url_resolver: Callable[[str], str] | None = None,
    ):
        from . import qqmusic_api as api

        self.loader = loader
        self.quality = quality
        if url_resolver is not None:
            self.url_resolver = url_resolver
        else:
            self.url_resolver = lambda mid: api.get_audio_url(mid, self.quality)
        self.ring = RingBuffer()
        self.streamer: TrackStreamer | None = None
        self.queue = PlaybackQueue()
        self.context = ""
        self.on_like: Callable[[], None] = lambda: logger.info("like 未接线")
        self._advance_timer: threading.Timer | None = None
        self._gen = 0
        self._fail_streak = 0

    def attach_streamer(self, streamer: TrackStreamer) -> None:
        self.streamer = streamer

    def load_context(self, key: str) -> None:
        self._gen += 1
        self.context = key
        songs = self.loader(key)
        mode = self.queue.mode
        self.queue = PlaybackQueue(mode=mode)
        self.queue.load(songs)
        self._play_current(reschedule=True)

    def _play_current(self, reschedule: bool) -> None:
        self._cancel_timer()
        song = self.queue.current()
        if song is None or self.streamer is None:
            return
        gen = self._gen
        try:
            url = self.url_resolver(song.mid)
        except Exception as exc:
            # 风控纪律：失败即顺延，不重试放大；连续 5 首失败（如登录过期）则熔断
            self._fail_streak += 1
            logger.warning("解析 %s 失败（%d/5）：%s", song.display_name(), self._fail_streak, exc)
            if self._fail_streak >= 5:
                logger.error("连续 5 首解析失败，停止自动推进。请检查登录态后 reload。")
                return
            self.control("next")
            return
        self._fail_streak = 0
        self.streamer.play(url)
        logger.info("正在播：%s", song.display_name())
        if reschedule and song.duration > 0:
            t = threading.Timer(song.duration + 2.0, self._on_track_end, args=(gen,))
            t.daemon = True
            self._advance_timer = t
            t.start()

    def _on_track_end(self, gen: int) -> None:
        if gen == self._gen:
            self.control("next")

    def _cancel_timer(self) -> None:
        if self._advance_timer is not None:
            self._advance_timer.cancel()
            self._advance_timer = None

    def control(self, cmd: str) -> dict:
        if cmd == "next":
            self.queue.next()
            self._play_current(reschedule=True)
        elif cmd == "prev":
            self.queue.prev()
            self._play_current(reschedule=True)
        elif cmd == "reload":
            self.load_context(self.context)
        elif cmd == "like":
            self.on_like()
        return self.status()

    def shutdown(self) -> None:
        self._gen += 1
        self._cancel_timer()
        if self.streamer is not None:
            self.streamer.stop()
        self.ring.close()

    def status(self) -> dict:
        snap = self.queue.snapshot()
        return {"context": self.context, **snap}


def make_server(host: str, port: int, app: RadioApp) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/stream.mp3"):
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    # 客户端先于首包连接时保持连接等待（电台语义），关闭时才断开
                    while not app.ring.is_closed():
                        chunk = app.ring.read(32 * 1024, timeout=1.0)
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            elif self.path.startswith("/status.json"):
                body = json.dumps(app.status(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path.startswith("/control"):
                qs = parse_qs(urlparse(self.path).query)
                cmd = (qs.get("cmd") or [""])[0]
                result = app.control(cmd) if cmd else {"error": "no cmd"}
                body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):
            logger.debug(fmt, *args)

    return ThreadingHTTPServer((host, port), Handler)
```

实现说明：`RingBuffer.read` 用单一 `_cond.wait` + deadline 实现超时/关闭语义；写端 `notify_all` 唤醒读者；`is_closed()` 供流 handler 在无数据时保持连接（电台语义）。若测试出现竞态 flaky，只允许在锁语义内调整（如加大 timeout），不许加 sleep hack。

- [ ] **Step 4: 运行测试通过**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_stream_server.py -v`
Expected: 全部 PASS；再连跑 `python -m pytest tests/test_stream_server.py -v` 三次确认稳定。

- [ ] **Step 5: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "feat(qqm): ffmpeg ring-buffer stream server + radio app glue"
```

---

### Task 9: radio_config.py — live_streams.sii 管理

**Files:**
- Create: `F:\research\ets2-qqmusic\qqm\radio_config.py`
- Create: `F:\research\ets2-qqmusic\tests\test_radio_config.py`

约定：我们的条目 Genre 字段固定为标记 `QQM`；首次安装做一次性备份 `live_streams.sii.qqm-backup.sii`；检测到 eurotrucks2.exe 运行时拒绝写入（游戏只在启动时读该文件，运行中改会被退出时的回写覆盖）。

- [ ] **Step 1: 写失败测试**

`tests/test_radio_config.py`:
```python
import pytest

from qqm import radio_config as rc


SAMPLE = """SiiNUnit
{
stream_data[0]: "http://a.example/x.mp3|Station A|Pop|English|128|0"
stream_data[1]: "http://b.example/y.mp3|Station B|Rock|German|192|0"
}
"""


def test_install_appends_marked_entries(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(SAMPLE, encoding="utf-8")
    rc.install(p, [("QQM 测试歌单", "http://127.0.0.1:23456/stream.mp3?ctx=111")])
    text = p.read_text(encoding="utf-8")
    assert "|QQM|" in text
    assert 'stream_data[2]:' in text
    assert text.rstrip().endswith("}")


def test_install_is_idempotent(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(SAMPLE, encoding="utf-8")
    rc.install(p, [("S1", "http://x/1")])
    rc.install(p, [("S1", "http://x/1"), ("S2", "http://x/2")])
    text = p.read_text(encoding="utf-8")
    assert text.count("|QQM|") == 2
    assert "S1" in text and "S2" in text


def test_install_creates_backup_once(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(SAMPLE, encoding="utf-8")
    rc.install(p, [("S1", "http://x/1")])
    backup = tmp_path / "live_streams.sii.qqm-backup.sii"
    first = backup.read_bytes()
    assert b"Station A" in first
    rc.install(p, [("S1", "http://x/1")])
    assert backup.read_bytes() == first


def test_install_creates_skeleton_if_missing(tmp_path):
    p = tmp_path / "live_streams.sii"
    rc.install(p, [("S1", "http://x/1")])
    text = p.read_text(encoding="utf-8")
    assert text.startswith("SiiNUnit")
    assert "|QQM|" in text


def test_remove_only_qqm_lines(tmp_path):
    p = tmp_path / "live_streams.sii"
    p.write_text(
        SAMPLE
        + 'stream_data[2]: "http://127.0.0.1:9/stream.mp3|QQM 歌单|QQM|Chinese|192|0"\n',
        encoding="utf-8",
    )
    removed = rc.remove(p)
    assert removed == 1
    text = p.read_text(encoding="utf-8")
    assert "Station A" in text and "|QQM|" not in text


def test_game_running_detection(monkeypatch):
    monkeypatch.setattr(rc, "_tasklist_output", lambda: b"eurotrucks2.exe   1234")
    assert rc.game_running() is True
    monkeypatch.setattr(rc, "_tasklist_output", lambda: b"INFO: No tasks are running")
    assert rc.game_running() is False


def test_install_refuses_while_game_running(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "game_running", lambda: True)
    p = tmp_path / "live_streams.sii"
    p.write_text(SAMPLE, encoding="utf-8")
    with pytest.raises(RuntimeError, match="正在运行"):
        rc.install(p, [("S1", "http://x/1")])


def test_install_force_bypasses_game_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "game_running", lambda: True)
    p = tmp_path / "live_streams.sii"
    p.write_text(SAMPLE, encoding="utf-8")
    rc.install(p, [("S1", "http://x/1")], force=True)
    assert "|QQM|" in p.read_text(encoding="utf-8")
```

- [ ] **Step 2: 运行确认失败**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_radio_config.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 radio_config.py**

`qqm/radio_config.py`:
```python
"""live_streams.sii 注册/移除 QQM 电台条目。

条目格式：stream_data[N]: "URL|名称|流派|语言|码率|收藏标记"
我们的流派字段固定为 "QQM" 作为识别与移除标记。
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER = "QQM"
BACKUP_SUFFIX = ".qqm-backup.sii"
_ENTRY_RE = re.compile(r"^\s*stream_data\[(\d+)\]\s*:")


def _tasklist_output() -> bytes:
    return subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq eurotrucks2.exe"],
        capture_output=True,
    ).stdout


def game_running() -> bool:
    return "eurotrucks2.exe" in _tasklist_output().lower()


def _ensure_skeleton(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    skeleton = "SiiNUnit\n{\n}\n"
    path.write_text(skeleton, encoding="utf-8")
    return skeleton


def _indices(text: str) -> list[int]:
    out = []
    for line in text.splitlines():
        m = _ENTRY_RE.match(line)
        if m:
            out.append(int(m.group(1)))
    return out


def install(path: Path, stations: list[tuple[str, str]], force: bool = False) -> int:
    """stations: [(显示名, 流URL)]。返回写入条数。游戏运行时拒绝除非 force。"""
    if not force and game_running():
        raise RuntimeError("检测到 ETS2 正在运行，请退出游戏后再执行（或加 --force）。")
    text = _ensure_skeleton(path)
    backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")

    kept_lines = [ln for ln in text.splitlines() if f"|{MARKER}|" not in ln]
    had_closing = bool(kept_lines) and kept_lines[-1].strip() == "}"
    body_lines = kept_lines[:-1] if had_closing else kept_lines

    next_idx = max(_indices("\n".join(body_lines)), default=-1) + 1
    new_lines = [
        f'stream_data[{next_idx + i}]: "{url}|{name}|{MARKER}|Chinese|192|0"'
        for i, (name, url) in enumerate(stations)
    ]
    out = "\n".join(body_lines + new_lines) + "\n}\n"
    path.write_text(out, encoding="utf-8")
    logger.info("已写入 %d 个 QQM 电台到 %s", len(new_lines), path)
    return len(new_lines)


def remove(path: Path) -> int:
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if f"|{MARKER}|" not in ln]
    removed = len(lines) - len(kept)
    if removed:
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return removed
```

- [ ] **Step 4: 运行测试通过**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_radio_config.py -v`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "feat(qqm): live_streams.sii install/remove with backup + game guard"
```

---

### Task 10: hotkeys.py — 全局热键（可选依赖）

**Files:**
- Create: `F:\research\ets2-qqmusic\qqm\hotkeys.py`
- Create: `F:\research\ets2-qqmusic\tests\test_hotkeys.py`

- [ ] **Step 1: 写失败测试**

`tests/test_hotkeys.py`:
```python
from qqm import hotkeys


class FakeKeyboard:
    def __init__(self):
        self.handlers = {}
        self.add_calls = []

    def add_hotkey(self, combo, fn):
        self.add_calls.append(combo)
        self.handlers[combo] = fn


def test_register_maps_controls():
    kb = FakeKeyboard()
    fired = []
    ok = hotkeys.register(
        kb,
        {
            "next": lambda: fired.append("next"),
            "prev": lambda: fired.append("prev"),
            "like": lambda: fired.append("like"),
        },
    )
    assert ok is True
    assert kb.add_calls == ["ctrl+alt+right", "ctrl+alt+left", "ctrl+alt+down"]
    kb.handlers["ctrl+alt+right"]()
    kb.handlers["ctrl+alt+left"]()
    kb.handlers["ctrl+alt+down"]()
    assert fired == ["next", "prev", "like"]


def test_missing_lib_returns_false(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "keyboard", None)  # import keyboard 会失败
    assert hotkeys.register(None, {}) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_hotkeys.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 hotkeys.py**

`qqm/hotkeys.py`:
```python
"""全局热键（可选）：需要 pip install keyboard。

Ctrl+Alt+Right 下一首 / Ctrl+Alt+Left 上一首 / Ctrl+Alt+Down 收藏当前曲。
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

_COMBOS = {
    "next": "ctrl+alt+right",
    "prev": "ctrl+alt+left",
    "like": "ctrl+alt+down",
}


def register(backend, actions: dict[str, Callable], combos: dict[str, str] | None = None) -> bool:
    """backend 是 keyboard 模块或兼容对象；传 None 时尝试 import。"""
    if backend is None:
        try:
            import keyboard as backend  # noqa: PLC0415
        except Exception:
            logger.warning("未安装 keyboard 库，热键不可用（pip install keyboard）")
            return False
    use = combos if combos is not None else _COMBOS
    for action, combo in use.items():
        fn = actions.get(action)
        if fn is not None:
            backend.add_hotkey(combo, fn)
    return True
```

- [ ] **Step 4: 运行测试通过**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_hotkeys.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "feat(qqm): optional global hotkeys"
```

---

### Task 11: cli.py — 命令入口

**Files:**
- Create: `F:\research\ets2-qqmusic\qqm\cli.py`
- Create: `F:\research\ets2-qqmusic\tests\test_cli.py`

命令总览：
- `python -m qqm.cli login` / `logout` / `status`
- `search <关键词>`
- `playlists`（列出自建+收藏歌单）
- `songs --playlist ID | --liked`
- `like <songid>`（手动收藏到我喜欢）
- `serve [--playlist ID | --liked] [--port N]`（起流服务 + 热键）
- `radio install --station "名称:<playlist_id|liked>" ... [--force]` / `radio remove`

电台 ctx 键约定：`liked` 或歌单 pid 字符串；电台 URL 形如 `http://127.0.0.1:23456/stream.mp3?ctx=<key>`。

- [ ] **Step 1: 写失败测试（路由断言，不打网络）**

`tests/test_cli.py`:
```python
import pytest

from qqm import cli


@pytest.fixture
def routed(monkeypatch):
    calls = []
    names = (
        "cmd_login", "cmd_logout", "cmd_status", "cmd_search",
        "cmd_playlists", "cmd_songs", "cmd_like",
        "cmd_serve", "cmd_radio_install", "cmd_radio_remove",
    )

    def mk(name):
        def fn(args, cfg):
            calls.append((name, args))
            return 0
        return fn

    for name in names:
        monkeypatch.setattr(cli, name, mk(name))
    return calls


def test_login(routed):
    cli.main(["login"])
    assert routed[-1][0] == "cmd_login"


def test_search(routed):
    cli.main(["search", "稻香"])
    name, args = routed[-1]
    assert name == "cmd_search" and args.keyword == "稻香"


def test_serve_playlist(routed):
    cli.main(["serve", "--playlist", "123"])
    name, args = routed[-1]
    assert name == "cmd_serve" and args.playlist == "123" and args.liked is False


def test_serve_liked(routed):
    cli.main(["serve", "--liked"])
    _, args = routed[-1]
    assert args.liked is True and args.playlist is None


def test_radio_install(routed):
    cli.main(["radio", "install", "--station", "我的歌单:123", "--station", "我喜欢:liked"])
    name, args = routed[-1]
    assert name == "cmd_radio_install"
    assert args.station == ["我的歌单:123", "我喜欢:liked"]
    assert args.force is False


def test_radio_remove(routed):
    cli.main(["radio", "remove"])
    assert routed[-1][0] == "cmd_radio_remove"


def test_songs_liked(routed):
    cli.main(["songs", "--liked"])
    _, args = routed[-1]
    assert args.liked is True
```

- [ ] **Step 2: 运行确认失败**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest tests/test_cli.py -v`
Expected: FAIL（cli 不存在）

- [ ] **Step 3: 实现 cli.py**

`qqm/cli.py`:
```python
"""命令行入口。示例：

  python -m qqm.cli login
  python -m qqm.cli playlists
  python -m qqm.cli songs --liked
  python -m qqm.cli serve --liked
  python -m qqm.cli radio install --station "我的歌单:123" --station "我喜欢:liked"
  python -m qqm.cli radio remove
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import threading

from . import qqmusic_api as api
from .config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qqm")


# ---------- 工具 ----------


def _require_cookie(cfg: Config) -> str:
    _, cookie = api.load_login()
    if not cookie:
        print("尚未登录，请先执行: python -m qqm.cli login")
        raise SystemExit(2)
    return cookie


def _plain_uin() -> str:
    uin = api.load_login()[0] or ""
    return uin.lstrip("o")


# ---------- 登录/查询命令 ----------


def cmd_login(args, cfg: Config) -> int:
    print("生成二维码…（将弹出系统看图窗口，用 QQ / QQ音乐 App 扫码确认）")
    try:
        result = api.qr_login(qr_path=str(cfg.qr_path), timeout_seconds=300)
    except TimeoutError as exc:
        print(f"登录失败：{exc}")
        return 1
    print(f"登录成功：{result['uin']}（凭证已存 {cfg.cookie_path}）")
    return 0


def cmd_logout(args, cfg: Config) -> int:
    api.clear_login()
    print("已清除本地登录态。")
    return 0


def cmd_status(args, cfg: Config) -> int:
    uin, _ = api.load_login()
    print(json.dumps({
        "logged_in": bool(uin),
        "uin": uin,
        "sii_path": str(cfg.sii_path),
        "ffmpeg": shutil.which("ffmpeg"),
    }, ensure_ascii=False))
    return 0


def cmd_search(args, cfg: Config) -> int:
    for i, s in enumerate(api.search_songs(args.keyword)):
        print(f"{i}: [{s.mid}] {s.display_name()} ({s.duration}s)")
    return 0


def cmd_playlists(args, cfg: Config) -> int:
    from . import library

    cookie = _require_cookie(cfg)
    for p in library.list_playlists(_plain_uin(), cookie):
        print(f"{p.kind:>7}  {p.pid:>12}  {p.count:>4}首  {p.name}")
    return 0


def cmd_songs(args, cfg: Config) -> int:
    from . import library

    cookie = _require_cookie(cfg)
    if args.liked:
        enc = library.get_encrypt_uin(_plain_uin(), cookie)
        songs = library.get_playlist_songs(0, cookie, liked=True, enc_uin=enc)
    elif args.playlist:
        songs = library.get_playlist_songs(int(args.playlist), cookie)
    else:
        print("需要 --playlist ID 或 --liked")
        return 2
    for i, s in enumerate(songs):
        print(f"{i}: [{s.mid}] {s.display_name()} ({s.duration}s)")
    return 0


def cmd_like(args, cfg: Config) -> int:
    from . import library

    cookie = _require_cookie(cfg)
    ok = library.like_songs([int(args.songid)], cookie)
    print("已收藏到「我喜欢」" if ok else "收藏失败")
    return 0 if ok else 1


# ---------- serve ----------


def _build_loader(cookie: str):
    from . import library

    def load(key: str):
        if key == "liked":
            enc = library.get_encrypt_uin(_plain_uin(), cookie)
            songs = library.get_playlist_songs(0, cookie, liked=True, enc_uin=enc)
        else:
            songs = library.get_playlist_songs(int(key), cookie)
        if not songs:
            raise SystemExit(f"歌单 {key} 为空或拉取失败")
        log.info("载入 %d 首：%s", len(songs), key)
        return songs

    return load


def cmd_serve(args, cfg: Config) -> int:
    from .stream_server import RadioApp, TrackStreamer, find_ffmpeg, make_server

    if not find_ffmpeg():
        print("找不到 ffmpeg：请安装或设置环境变量 QQM_FFMPEG_PATH 指向 ffmpeg.exe")
        return 1
    cookie = _require_cookie(cfg)
    ctx_key = "liked" if args.liked else str(args.playlist)

    app = RadioApp(loader=_build_loader(cookie), quality=cfg.quality)
    app.attach_streamer(TrackStreamer(app.ring))

    def do_like():
        cur = app.queue.current()
        if cur is None:
            return
        from . import library

        ok = library.like_songs([cur.songid], cookie)
        log.info("收藏 %s：%s", cur.display_name(), "成功" if ok else "失败")

    app.on_like = do_like

    server = make_server("127.0.0.1", args.port, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        from . import hotkeys
        hotkeys.register(None, {
            "next": lambda: app.control("next"),
            "prev": lambda: app.control("prev"),
            "like": do_like,
        })
    except Exception as exc:  # 热键失败不阻塞
        log.warning("热键注册失败：%s", exc)

    print(f"流地址: http://127.0.0.1:{args.port}/stream.mp3?ctx={ctx_key}")
    print("状态:   http://127.0.0.1:{0}/status.json".format(args.port))
    print("控制:   POST http://127.0.0.1:{0}/control?cmd=next|prev|reload|like".format(args.port))
    print("热键:   Ctrl+Alt+Right 下一首 / Ctrl+Alt+Left 上一首 / Ctrl+Alt+Down 收藏（需 keyboard 库）")
    print("Ctrl+C 退出。")
    try:
        app.load_context(ctx_key)
        threading.Event().wait()  # 挂起主线程直到 Ctrl+C
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
        server.shutdown()
    return 0


# ---------- radio ----------


def _parse_station(spec: str) -> tuple[str, str]:
    """'我的歌单:123' -> ('我的歌单', 'http://.../stream.mp3?ctx=123')"""
    name, _, key = spec.rpartition(":")
    if not name or not key:
        raise SystemExit(f"--station 格式应为 名称:<playlist_id|liked>，收到 {spec!r}")
    url = f"http://127.0.0.1:23456/stream.mp3?ctx={key}"
    return name, url


def cmd_radio_install(args, cfg: Config) -> int:
    from . import radio_config

    stations = [_parse_station(s) for s in args.station]
    count = radio_config.install(cfg.sii_path, stations, force=args.force)
    print(f"已写入 {count} 个电台条目到 {cfg.sii_path}")
    print("注意：游戏只在启动时读取该文件——若游戏正在运行，退出后重开生效。")
    return 0


def cmd_radio_remove(args, cfg: Config) -> int:
    from . import radio_config

    removed = radio_config.remove(cfg.sii_path)
    print(f"已移除 {removed} 个 QQM 电台条目。")
    return 0


# ---------- argparse 装配 ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qqm", description="ETS2 QQ 音乐伴侣")
    sub = p.add_subparsers(required=True)

    sub.add_parser("login").set_defaults(fn=cmd_login)
    sub.add_parser("logout").set_defaults(fn=cmd_logout)
    sub.add_parser("status").set_defaults(fn=cmd_status)

    sp = sub.add_parser("search")
    sp.add_argument("keyword")
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("playlists")
    sp.set_defaults(fn=cmd_playlists)

    sp = sub.add_parser("songs")
    sp.add_argument("--playlist", default=None)
    sp.add_argument("--liked", action="store_true")
    sp.set_defaults(fn=cmd_songs)

    sp = sub.add_parser("like")
    sp.add_argument("songid")
    sp.set_defaults(fn=cmd_like)

    sp = sub.add_parser("serve")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--playlist")
    g.add_argument("--liked", action="store_true")
    sp.add_argument("--port", type=int, default=23456)
    sp.set_defaults(fn=cmd_serve)

    rp = sub.add_parser("radio")
    rsub = rp.add_subparsers(required=True)
    ip = rsub.add_parser("install")
    ip.add_argument("--station", action="append", required=True,
                    help='格式 "名称:<playlist_id|liked>"，可多次')
    ip.add_argument("--force", action="store_true")
    ip.set_defaults(fn=cmd_radio_install)
    rm = rsub.add_parser("remove")
    rm.set_defaults(fn=cmd_radio_remove)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    cfg = Config.load()
    return ns.fn(ns, cfg)


if __name__ == "__main__":
    sys.exit(main())
```

注意：测试 monkeypatch 的处理器名是 `cmd_login` 等——与模块级函数名一致，路由断言成立（`ns.fn` 即被 patch 后的函数）。`main()` 在测试里直接调用并返回 0。

- [ ] **Step 4: 手工冒烟（不打网络的部分）**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m qqm.cli status; python -m qqm.cli --help`
Expected: 输出 JSON（logged_in=false 等）与帮助文本，无异常

- [ ] **Step 5: 运行全部测试**

Run: `Set-Location "F:\research\ets2-qqmusic"; python -m pytest -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; git add -A; git commit -m "feat(qqm): cli entrypoints (login/search/serve/radio)"
```

---

### Task 12: README + 实机验证清单 + 收尾

**Files:**
- Create: `F:\research\ets2-qqmusic\README.md`
- Modify: 无代码改动（若有修复则一并提交）

- [ ] **Step 1: 写 README.md**

`README.md` 内容要点（完整写出）：
```markdown
# ETS2 QQ音乐伴侣播放器（qqm）

在《欧洲卡车模拟2》里听自己的 QQ 音乐歌单：扫码登录后，把"我喜欢/自建歌单/收藏歌单"
变成车载网络电台。个人学习用途，需要自备 QQ 音乐会员账号。

## 安装

1. Python 3.10+
2. 安装 [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) 并确保 `ffmpeg` 在 PATH
   （或设环境变量 `QQM_FFMPEG_PATH` 指向 ffmpeg.exe）
3. `pip install -r requirements-dev.txt`（可选：`pip install keyboard` 启用全局热键）

## 使用流程

```
python -m qqm.cli login                # 弹出二维码，手机 QQ/QQ音乐 扫码
python -m qqm.cli playlists            # 看歌单列表
python -m qqm.cli serve --liked        # 把"我喜欢"做成电台流（保持窗口开着）
python -m qqm.cli radio install --station "我的歌单:123456" --station "我喜欢:liked"
                                       # 注册进游戏电台列表（游戏需处于关闭状态）
```

启动游戏 → 按 R 打开收音机 → Internet Radio 里找你的歌单名 → 切台即切歌单。

## 游戏内控制

- 切歌/暂停：游戏内收音机开关与音量即控制
- 下一首/上一首：全局热键 Ctrl+Alt+Right / Ctrl+Alt+Left（需 keyboard 库）
- HTTP 控制：`POST http://127.0.0.1:23456/control?cmd=next|prev|reload|like`
- 当前曲目：`http://127.0.0.1:23456/status.json`

## 已知限制

- 电台模式没有进度条/暂停（网络电台语义）；VIP 歌需登录且账号有有效会员
- 登录态过期后 VIP 歌自动顺延失败并提示重新扫码
- live_streams.sii 只在游戏启动时读取；改完要重启游戏
- 凭证明文存于 data/（已被 .gitignore），请勿外传

## 致谢

- [L-1124/QQMusicApi](https://github.com/L-1124/QQMusicApi) —— 扫码登录/接口参考
- [copws/qq-music-api](https://github.com/copws/qq-music-api) —— 搜索/播放流端点
- Spica-Chatbot 项目 —— 移植底本
```

- [ ] **Step 2: 实机验证清单（需要用户配合，逐项打勾记录结果）**

按顺序执行并把每步结果记录到本计划下方"实机验证记录"小节：

1. `python -m qqm.cli login` → 二维码弹出 → 手机扫码 → 提示登录成功、data/qqmusic_cookie.json 生成
2. `python -m qqm.cli playlists` → 能列出至少一个自建歌单和"我喜欢"
3. `python -m qqm.cli songs --liked` → 能列出歌曲（含歌名/歌手/时长）
4. `python -m qqm.cli serve --liked` → 控制台显示"正在播：xxx"；浏览器/VLC 打开 `http://127.0.0.1:23456/stream.mp3` 能听到声音（约 2-5 秒缓冲）
5. 浏览器打开 `/status.json` 显示当前曲名；`curl -X POST "http://127.0.0.1:23456/control?cmd=next"` 能切歌
6. （安装 keyboard 后）Ctrl+Alt+Right 切下一首生效
7. 关闭游戏状态下 `radio install --station "我喜欢:liked"` → 用记事本打开 live_streams.sii 确认新条目带 `|QQM|`
8. 启动 ETS2 → R 键 → Internet Radio → 选"我喜欢" → 游戏内出声、仪表盘显示台名
9. 点一首 VIP 歌验证登录态生效（能播）；临时改坏 Cookie 验证失败路径提示重新扫码
10. 全程观察控制台无异常堆栈

- [ ] **Step 3: 根据实测修正（如有）**

字段形状对不上（歌单列表/CgiGetDiss 响应）时：先用 `_post_musicu` 的原始响应打印核对（可临时加 `--debug-dump` 或直接 REPL），修 `library.py` 解析器与 fixture，保持测试绿。

- [ ] **Step 4: 全量回归 + Commit**

```powershell
Set-Location "F:\research\ets2-qqmusic"; python -m pytest -v; git add -A; git commit -m "docs: readme + smoke-test fixes"
```

---

## 实机验证记录

> 执行 Task 12 Step 2 时填写：

| # | 项目 | 结果 | 备注 |
|---|---|---|---|
| 1 | 扫码登录 | | |
| 2 | 歌单列表 | | |
| 3 | 我喜欢列表 | | |
| 4 | 流服务可听 | | |
| 5 | 状态/控制接口 | | |
| 6 | 热键 | | |
| 7 | sii 注册 | | |
| 8 | 游戏内收音机 | | |
| 9 | VIP 歌/失效路径 | | |
| 10 | 无异常 | | |

## 风险与执行注意事项（给执行者）

1. **不要改动 Task 4 的任何端点参数**——那是实机验证过的流程；mock 对不上时改 mock。
2. Task 6 写操作 param 若与 L-1124 上游源码不一致，以上游为准同步修改实现与测试。
3. 所有 QQ 请求必须直连（`ProxyHandler({})`），日志不得输出 musickey/qm_keyst（已有 mask_credentials）。
4. live_streams.sii 操作前确认游戏未运行；提供 `--force` 仅作逃生门。
5. RingBuffer 若出现 flaky，只许在锁语义内调整（加大 timeout / 调整 wait 粒度），不许加 sleep hack。

