# Social Position Tracker

一个本地 `Streamlit` 小应用，用来盯社交平台上的公开发言，并抽取：

- 提到的 `ticker`
- 观点倾向与买卖态度
- 疑似仓位动作线索
- 对应原文证据和来源链接

> 本工具仅基于公开内容追踪观点和疑似仓位线索，不代表作者真实账户持仓，不构成投资建议。

## 启动

```bash
streamlit run social_position_tracker_app.py
```

## 当前支持

- 英文和中文公开内容
- X、Reddit、公开网页、搜索结果等公开来源
- A 股、美股、ETF 的初步识别
- 通过 `social_tracker/ticker_aliases.json` 将中文名称、代码、英文别名映射到 `canonical_ticker`
- X 公开主页 / 单条帖子抓取（通过 `r.jina.ai` 做可读化抓取）
- 可选 DeepSeek / OpenAI 兼容接口做增强抽取
- 命令行单次刷新，可接系统定时任务

## 说明

- X 直抓在很多环境里会受登录、反爬和 JS 渲染限制，所以当前版本把它设计成“搜索结果补抓 + 网页抓取 + 可扩展收集器”。
- 当前版本优先用 `r.jina.ai/http://x.com/...` 读取公开 X 页面，这比直接请求 `x.com` 稳定很多。
- 页面里的“作者疑似持仓动态”仅表示公开表达下的疑似仓位线索，不代表作者真实账户持仓。
- 如果你后面要接自己的 cookie、代理或者更强的爬虫源，这个结构可以继续往里加。

## 命令行刷新

```bash
python3 run_social_tracker.py
```

这会按配置抓一轮，并把结果写到 `app_data/snapshots.json`。

## 后台自动跑

仓库里已经给你放了两个模板：

- [scripts/run_social_tracker.sh](/Users/shark-li/Documents/New%20project/scripts/run_social_tracker.sh)
- [scripts/com.social.tracker.example.plist](/Users/shark-li/Documents/New%20project/scripts/com.social.tracker.example.plist)

`plist` 里默认是每 `600` 秒跑一次。你可以按需改成 300、1800、3600 秒。

## Secrets 配置

不要把 key 写进代码或提交到仓库。

本项目会按下面顺序读取 LLM 密钥：

1. `DEEPSEEK_API_KEY`
2. `OPENAI_API_KEY`
3. `LLM_API_KEY`

本地运行时你可以：

- 配环境变量
- 或使用 `.streamlit/secrets.toml`

示例：

```toml
DEEPSEEK_API_KEY = "your-key"
```

## Streamlit Community Cloud 部署

1. 把这个项目推送到 GitHub。
2. 打开 [Streamlit Community Cloud](https://share.streamlit.io/)。
3. 选择 `New app`。
4. 选择你的 `repo`、`branch`，入口文件填 `social_position_tracker_app.py`。
5. 在应用的 `Secrets` 里配置需要的密钥，例如：

```toml
DEEPSEEK_API_KEY = "your-key"
```

6. 点击 `Deploy`。

部署后说明：

- `app_data/` 会自动创建。
- 如果没有 `app_data/snapshots.json`，程序会自动初始化为空数组。
- 本地运行方式不变，仍然可以继续用 `streamlit run social_position_tracker_app.py`。
- Streamlit Community Cloud 的部署方式保持不变。
