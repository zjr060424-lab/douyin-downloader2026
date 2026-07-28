# dydownload

Windows 桌面端抖音 / B 站下载工具。通过浏览器扩展把当前登录会话的 Cookie 安全地发送到本机程序，支持图形界面、命令行、下载进度、断点续传和 B 站 DASH 音视频合流。

> 本项目仅供学习和个人数据备份。请遵守平台服务条款、版权规定和当地法律，只下载自己有权保存的内容。

## 功能

| 平台 | 支持内容 | 说明 |
| --- | --- | --- |
| 抖音 | 视频、图文/图集、实况图、背景音乐 | 自动解析分享文本、短链接和完整链接 |
| Bilibili | 普通 BV/AV 视频、多 P 视频 | 支持画质选择、DASH 下载和 ffmpeg 无损合流 |

其他能力：

- Chrome / Edge Manifest V3 扩展自动获取并推送 Cookie
- GUI 与 CLI 两种使用方式
- 同一文件并发保护、断点续传及文件长度校验
- 自动发现 `127.0.0.1:18921-18925` 上的本地服务
- Cookie 状态检测和可读的错误提示
- 中文标题文件名和 Windows 打包支持

## 普通用户快速开始

### 1. 下载便携版

从 [Releases](https://github.com/zjr060424-lab/douyin-downloader2026/releases) 下载最新便携包并完整解压。推荐的发布包结构如下：

```text
easy_use/
├── dydownload.exe
├── ffmpeg.exe
├── 使用教程.md
└── extension/
```

`ffmpeg.exe` 用于 B 站 DASH 音视频合流，不需要手动运行。仅使用抖音下载时可以不带 ffmpeg。

### 2. 安装浏览器扩展

1. Chrome 打开 `chrome://extensions/`，Edge 打开 `edge://extensions/`。
2. 开启“开发者模式”。
3. 点击“加载已解压的扩展程序”。
4. 选择便携包中的 `extension` 文件夹。
5. 将 dydownload 扩展固定到浏览器工具栏。

### 3. 推送 Cookie

1. 在浏览器中登录抖音或 B 站。
2. 双击运行 `dydownload.exe`，保持窗口开启。
3. 在对应网站页面点击 dydownload 扩展。
4. 点击“推送到 CLI”。

Cookie 仅发送到本机回环地址，并保存在 `%USERPROFILE%\.dydownload`。不要向他人发送该目录中的文件。

### 4. 下载

复制视频链接，粘贴到程序窗口，保持“自动识别”或选择对应平台，然后点击下载。成品默认保存在 EXE 同目录的 `downloads` 文件夹。

扩展弹窗也支持直接读取当前页面链接并发起下载。

## 支持的链接

抖音：

```text
https://v.douyin.com/xxxxx/
https://www.douyin.com/video/{id}
https://www.douyin.com/note/{id}
https://www.iesdouyin.com/share/video/{id}/
```

Bilibili：

```text
https://www.bilibili.com/video/BVxxxxxxxxxx
https://www.bilibili.com/video/av123456
https://b23.tv/xxxxx
```

## 从源码运行

### 环境要求

- Windows 10/11
- Conda
- Python 3.10
- Chrome 或 Edge
- ffmpeg，可选；B 站 DASH 自动合流时必需

### 安装

```powershell
git clone https://github.com/zjr060424-lab/douyin-downloader2026.git
cd douyin-downloader2026
conda env create -f environment.yml
conda activate dydownload
```

安装浏览器扩展时，选择仓库中的 `extension` 文件夹。

### 启动 GUI

```powershell
python -m dydownload.gui
```

### 使用 CLI

```powershell
# 检查 Cookie 状态
python -m dydownload.cli status

# 下载抖音内容
python -m dydownload.cli download "https://v.douyin.com/xxxxx/"

# 下载 B 站普通视频
python -m dydownload.cli download "https://www.bilibili.com/video/BVxxxxxxxxxx"

# 指定平台、画质、多 P 和合流选项
python -m dydownload.cli download "视频链接" `
  --platform bilibili `
  --quality 80 `
  --parts all `
  --mux

# 单独启动本地 Cookie 接收服务
python -m dydownload.cli serve
```

B 站画质代码：`80=1080p`、`112=1080p+`、`116=1080p60`、`120=4K`。实际可用画质取决于账号权限和视频源。

## 测试

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python tests/smoke_tuwen.py
python tests/smoke_bilibili.py
```

测试覆盖本地服务来源限制、WBI 签名、AV/BV 路由、Cookie 状态、并发保护、断点续传和 Unicode 路径合流等关键行为。

## 构建 Windows EXE

```powershell
conda activate dydownload
pyinstaller --clean --noconfirm dydownload.spec
```

构建结果位于 `dist\dydownload.exe`。制作便携包时，将以下内容放在同一目录：

```text
dydownload.exe
ffmpeg.exe
extension/
使用教程.md
```

项目不会把大型 ffmpeg 二进制提交进 Git 仓库；请在 Release 资产中分发便携包。

## 数据与安全

- 本地服务只绑定 `127.0.0.1`，不会监听局域网或公网地址。
- 浏览器请求仅接受 Chrome / Firefox 扩展来源，普通网页来源会被拒绝。
- 请求体限制为 1 MiB，下载任务状态数量有上限。
- Cookie 文件和下载内容已被 `.gitignore` 排除。
- 提交代码前仍建议运行 `git status` 并检查是否包含账号信息。

## 已知限制

- 目前主要支持 Windows，其他系统未经过完整验证。
- B 站番剧、影视、DRM 或付费内容不在支持范围内。
- B 站 1080p 及以上画质通常需要有效登录 Cookie。
- 平台接口可能随时变化，解析失败时请先更新到最新版本并重新推送 Cookie。
- 下载中关闭程序会中断当前任务，但 `.part` 文件可用于后续续传。

## 项目结构

```text
.
├── dydownload/          # Python GUI、CLI、服务端与下载管线
│   ├── bilibili/        # B 站 API、WBI 签名与解析
│   └── js/              # 抖音签名脚本
├── extension/           # Chrome / Edge Manifest V3 扩展
├── tests/               # 回归测试与 smoke 测试
├── dydownload.spec      # PyInstaller 构建配置
├── environment.yml      # Conda 环境
└── pyproject.toml       # Python 包元数据
```

## 免责声明

本项目不提供绕过付费、DRM、访问控制或平台权限的功能。使用者应自行承担因使用本项目产生的责任。
