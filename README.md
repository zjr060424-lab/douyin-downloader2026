# dydownload — 抖音无水印视频下载工具

> 仅供学习研究，不得用于商业用途

通过浏览器插件自动抓取抖音 Cookie → 本地 HTTP 服务接收 → 解析并下载无水印视频。

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

### 3. 下载视频

1. 浏览器打开 [douyin.com](https://www.douyin.com) 并登录
2. 点击浏览器工具栏的 dydownload 插件图标，点「推送到 CLI」
3. 在抖音浏览视频，点插件图标 → 「下载无水印视频」
4. 或复制视频链接，粘贴到 dydownload.exe 窗口的输入框 → 点「下载」

视频保存在 exe 所在目录的 `downloads/` 文件夹。

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

# 下载视频
python -m dydownload download "https://v.douyin.com/xxxxx/"

# 查看 Cookie 状态
python -m dydownload status

# 测试 a_bogus 签名
python -m dydownload test "https://www.douyin.com/video/xxxxx"
```

### 4. 自行打包

```bash
conda run -n dydownload pyinstaller dydownload.spec --distpath ./dist --workpath ./build --noconfirm
```

---

## 浏览器扩展说明

扩展安装后会自动运行：

- **自动推送**：每 5 分钟检查一次 cookie 是否有变化，有变化则推送到 CLI
- **手动推送**：点击扩展图标，在弹出窗口中点击「推送到 CLI」
- **一键下载**：浏览视频时打开插件，地址已自动填好，点击下载即可
- **复制 Cookie**：点击「复制 Cookie」可将完整 cookie 字符串复制到剪贴板

---

## 项目结构

```
dydownload/
├── dydownload/           # Python CLI 包
│   ├── cli.py            # 命令入口
│   ├── gui.py            # tkinter GUI 入口
│   ├── api_client.py     # 抖音 HTTP 请求
│   ├── signature.py      # a_bogus 签名
│   ├── video_parser.py   # 视频信息解析
│   ├── downloader.py     # 流式下载
│   ├── server.py         # Cookie 接收服务
│   ├── cookie_manager.py # Cookie 管理
│   ├── config.py         # 配置常量
│   └── js/               # 签名 JS 脚本
├── extension/            # 浏览器扩展 (Chrome/Edge)
│   ├── manifest.json
│   ├── background/       # 后台服务
│   ├── popup/            # 弹出界面
│   └── content/          # 页面注入脚本
├── dydownload.spec       # PyInstaller 打包配置
└── pyproject.toml
```
