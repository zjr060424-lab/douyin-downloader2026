# dydownload — 抖音视频下载工具
# 「仅供学习研究，不得用于商业用途」
通过浏览器插件自动抓取抖音 Cookie → 本地 HTTP 服务接收 → Python CLI 解析并下载无水印视频。

## 安装

### 1. 创建 Conda 环境

```bash
conda env create -f environment.yml
conda activate dydownload
```

### 2. 安装浏览器扩展

1. 打开 Chrome 或 Edge，进入 `chrome://extensions/`
2. 开启「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择 `extension/` 目录
5. 扩展图标会出现在浏览器工具栏

## 使用

### 下载视频

```bash
python -m dydownload download "https://v.douyin.com/xxxxx/"
```

执行流程：
1. 自动启动本地 Cookie 接收服务（127.0.0.1:18921）
2. 等待浏览器插件推送 Cookie（需在浏览器中打开 douyin.com 并登录）
3. 解析视频链接，提取无水印播放地址
4. 显示视频信息（标题、作者、时长、分辨率）
5. 流式下载，显示进度条

视频默认保存在 `./downloads/` 目录。

### 检查 Cookie 状态

```bash
python -m dydownload status
```

### 仅启动 Cookie 服务

```bash
python -m dydownload serve
```

## 浏览器扩展说明

扩展安装后会自动运行：

- **自动推送**：每 5 分钟检查一次 cookie 是否有变化，有变化则推送到 CLI
- **手动推送**：点击扩展图标，在弹出窗口中点击「推送到 CLI」
- **复制 Cookie**：点击「复制 Cookie」可将完整 cookie 字符串复制到剪贴板

弹出窗口会显示：
- CLI 服务是否在线
- 当前 cookie 数量和关键字段状态
- 上次推送时间

## 项目结构

```
dydownload/
├── dydownload/           # Python CLI 包
│   ├── cli.py            # 命令入口
│   ├── api_client.py     # 抖音 HTTP 请求
│   ├── video_parser.py   # 视频信息解析
│   ├── downloader.py     # 流式下载
│   ├── server.py         # Cookie 接收服务
│   ├── cookie_manager.py # Cookie 管理
│   ├── config.py         # 配置常量
│   └── utils.py          # 工具函数
├── extension/            # 浏览器扩展 (Chrome/Edge)
│   ├── manifest.json
│   ├── background/       # 后台服务
│   ├── popup/            # 弹出界面
│   └── content/          # 页面注入脚本
├── environment.yml       # Conda 环境定义
└── pyproject.toml
```
