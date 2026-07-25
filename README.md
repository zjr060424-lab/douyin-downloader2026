# dydownload — 抖音 / B 站下载工具

> 仅供学习研究，不得用于商业用途

通过浏览器插件自动抓取抖音 / B 站 Cookie → 本地 HTTP 服务接收 → 解析并下载无水印视频或图集（图集自动归档为子文件夹，含实况图 + 背景音乐）。

支持链接：

抖音：
- 短链：`https://v.douyin.com/xxxxx/`
- 视频页：`https://www.douyin.com/video/{id}`
- 图文/图集：`https://www.douyin.com/note/{id}`
- 分享页：`https://www.iesdouyin.com/share/video/{id}/`

B 站（普通视频）：
- 短链：`https://b23.tv/xxxxx`
- 视频页：`https://www.bilibili.com/video/BVxxxxxxxxxx` 或 `https://www.bilibili.com/video/av{数字}`
- 番剧 / bangumi 暂不支持

---

## 安装与使用（普通用户 — 直接下载 .exe）

### 1. 下载程序

从 [Releases](../../releases) 页面下载最新版 `dydownload.exe`，放到任意目录，双击运行。

### 2. 安装浏览器扩展

1. 打开 Chrome 或 Edge，进入 `chrome://extensions/`
2. 开启「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择 `extension/` 目录
5. 扩展图标会出现在浏览器工具栏

### 3. 下载视频或图集

1. 浏览器打开 [douyin.com](https://www.douyin.com) 并登录
2. 点击浏览器工具栏的 dydownload 插件图标，点「推送到 CLI」
3. 在抖音浏览视频或图集，点插件图标 → 「下载无水印视频」（插件自动识别视频页/图文页）
4. 或复制链接，粘贴到 dydownload.exe 窗口的输入框 → 点「下载」

文件保存在 exe 所在目录的 `downloads/` 文件夹：
- 抖音视频 → `downloads/<标题>-<id>.mp4`
- 抖音图集 → `downloads/<标题>-<id>/01.jpg, 02.jpg …` + `xx_live.mp4`（实况图）+ `bgm.mp3`（背景音乐）
- B 站单 P → `downloads/<标题>-<bvid>.mp4`
- B 站多 P → `downloads/<标题>-<bvid>_P01.mp4`, `_P02.mp4` …
- B 站 DASH 合流失败时保留 `<标题>-<bvid>_video.m4s` + `_audio.m4s`

---

## 安装与使用（开发者 — 命令行）

### 1. 创建 Conda 环境

```bash
conda env create -f environment.yml
conda activate dydownload
```

### 2. 安装浏览器扩展

同上。

### 3. 命令

```bash
# 启动后端服务
python -m dydownload serve

# 下载抖音视频或图集
python -m dydownload download "https://v.douyin.com/xxxxx/"
python -m dydownload download "https://www.douyin.com/note/xxxxx/"

# 下载 B 站普通视频（自动识别链接）
python -m dydownload download "https://www.bilibili.com/video/BV1xxxxxxxxxx"
python -m dydownload download "https://b23.tv/xxxxx"

# 显式指定平台 / 画质 / 多 P / 合流
python -m dydownload download "https://www.bilibili.com/video/BV1xxxxxxxxxx" \
    --platform bilibili --quality 80 --parts all --mux

# 查看 Cookie 状态
python -m dydownload status

# 测试 a_bogus 签名（仅抖音）
python -m dydownload test "https://www.douyin.com/video/xxxxx"
```

### 4. 自行打包

```bash
conda run -n dydownload pyinstaller dydownload.spec --distpath ./dist --workpath ./build --noconfirm
```

---

## 浏览器扩展说明

扩展安装后会自动运行：

- **自动推送**：每 5 分钟检查一次 cookie 是否有变化，有变化则推送到 CLI（抖音、B 站分别写入 `~/.dydownload/cookies.txt` 和 `~/.dydownload/cookies.bilibili.txt`）
- **手动推送**：点击扩展图标，在弹出窗口中点击「推送到 CLI」
- **一键下载**：浏览视频时打开插件，地址已自动填好（抖音/B 站自动识别），可选择平台、画质、多 P、DASH、ffmpeg 合流
- **复制 Cookie**：点击「复制 Cookie」会将抖音和 B 站 cookie 一起写入剪贴板

### B 站额外说明

- 1080p 及以上画质需登录 SESSDATA，匿名只能取到 480p 左右
- 登录后请在 [bilibili.com](https://www.bilibili.com) 任意页面打开扩展 →「推送到 CLI」
- 默认使用 DASH 流（视频 + 音频分轨），需要 ffmpeg 自动合流；如未安装 ffmpeg 可放入 `~/.dydownload/ffmpeg.exe` 或加入 PATH，关闭合流使用 `--no-mux`
- 番剧（`/bangumi/play/ep...` 或 `ss...`）暂不支持
- 浏览器扩展需重新加载（`chrome://extensions` →「重新加载」）才可识别 `*.bilibili.com`

---

## 项目结构

```
dydownload/
├── dydownload/           # Python CLI 包
│   ├── cli.py            # 命令入口
│   ├── gui.py            # tkinter GUI 入口
│   ├── api_client.py     # 抖音 HTTP 请求
│   ├── signature.py      # a_bogus 签名
│   ├── video_parser.py   # 视频/图集信息解析
│   ├── downloader.py     # 流式下载（视频 + 图片）
│   ├── pipeline.py       # 共享下载管线（自动识别抖音 / B 站）
│   ├── mux.py            # ffmpeg 发现与 DASH 合流
│   ├── server.py         # Cookie 接收 + 一键下载服务（多平台）
│   ├── cookie_manager.py # 双平台 Cookie 管理
│   ├── config.py         # 配置常量
│   ├── js/               # 抖音签名 JS 脚本
│   └── bilibili/         # B 站子包
│       ├── api_client.py # WBI 签名 + /nav + /view + /playurl
│       ├── signature.py  # WBI mixin_key
│       └── video_parser.py # 视频元信息解析
├── extension/            # 浏览器扩展 (Chrome/Edge)
│   ├── manifest.json
│   ├── background/       # 后台服务
│   ├── popup/            # 弹出界面
│   └── content/          # 页面注入脚本
├── dydownload.spec       # PyInstaller 打包配置
└── pyproject.toml
```
