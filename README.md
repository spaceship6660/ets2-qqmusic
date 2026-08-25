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
