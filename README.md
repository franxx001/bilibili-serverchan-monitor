# B站动态监控 → Server酱 Turbo 推送

基于 **GitHub Actions** 的 B站 UP 主动态监控系统，通过 **Server酱 Turbo** 推送到微信。零服务器、纯 Python 标准库、开箱即用。

## 功能

- 🔍 通过 B站 API（含 WBI 签名）监控指定 UID 的空间动态
- 📲 通过 Server酱 Turbo 实时推送到**微信**
- 📦 零依赖，仅用 Python 标准库
- 💾 状态持久化到 Git，避免重复推送
- ⏰ GitHub Actions 定时运行（可自定义间隔）
- 🖼️ 支持图文动态、视频投稿、专栏文章等多种动态类型

## 快速开始（3 步）

### 第 1 步：获取 Server酱 Turbo SendKey

1. 打开 [Server酱 Turbo](https://sct.ftqq.com/)
2. 微信扫码登录
3. 点击「SendKey」→ 复制你的 SendKey
4. 微信关注「方糖」公众号（接收推送）

### 第 2 步：Fork 并配置

1. Fork 本仓库到你的 GitHub
2. 编辑 `monitor.py` 第 11 行，把 `UID` 改成你想监控的 UP 主 UID：

```python
UID = "3546768189622669"  # 改成你要监控的 UP 主 UID
```

> UID 怎么找？打开 UP 主 B站主页 `https://space.bilibili.com/3546768189622669`，网址中这串数字就是 UID。

3. 在仓库 **Settings → Secrets and variables → Actions** 中添加 Secret：

| 名称 | 值 |
|------|-----|
| `SERVERCHAN_SENDKEY` | 你第 1 步复制的 SendKey |

### 第 3 步：启用 GitHub Actions

1. 进入仓库的 **Actions** 标签页
2. 点击「I understand my workflows, go ahead and enable them」
3. 选择「B站动态监控」→ **Run workflow** 手动测试一次
4. 微信上应该会收到一条推送消息

搞定。以后每 10 分钟自动检查一次，UP 主发新动态就会推送到你微信。

## 自定义配置

### 修改检查间隔

编辑 `.github/workflows/monitor.yml` 的 `cron` 表达式：

```yaml
schedule:
  - cron: "*/10 * * * *"   # 每10分钟
  # - cron: "*/5 * * * *"  # 每5分钟
  # - cron: "*/30 * * * *" # 每30分钟
```

⚠️ 不建议小于 5 分钟，否则可能触发 B站反爬或 GitHub Actions 限制。

### 监控多个 UP 主

在 `monitor.py` 中把 `UID` 改成用列表循环即可（需要稍微改一下代码逻辑），或为每个 UP 主创建单独的 workflow。

## 项目结构

```
├── .github/workflows/monitor.yml  # GitHub Actions 工作流
├── monitor.py                     # 核心监控脚本
├── data/state.json                # 状态持久化（自动更新）
└── requirements.txt               # 依赖（空，仅标准库）
```

## 工作原理

1. GitHub Actions 每 10 分钟自动运行 `monitor.py`
2. 脚本通过 B站 API（带 WBI 签名）获取 UP 主最新动态
3. 对比 `data/state.json` 中记录的动态 ID，识别新动态
4. 新动态通过 Server酱 Turbo API 推送到微信
5. 更新 `state.json`，由 GitHub Actions 自动提交回仓库

## 动态类型支持

| 类型 | 说明 | 推送 |
|------|------|------|
| MAJOR_TYPE_ARCHIVE | 视频投稿 | ✅ |
| MAJOR_TYPE_DRAW | 图文动态 | ✅ |
| MAJOR_TYPE_ARTICLE | 专栏文章 | ✅ |
| MAJOR_TYPE_OPUS | 图文短动态 | ✅ |
| MAJOR_TYPE_LIVE_RCMD | 直播推荐 | ✅ |
| MAJOR_TYPE_NONE | 纯文字/转发 | ✅ |

## License

MIT
