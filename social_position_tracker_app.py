from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from social_tracker.pipeline import run_pipeline
from social_tracker.storage import load_config, load_snapshots, resolve_llm_config, save_config


st.set_page_config(page_title="社交持仓雷达", page_icon="📡", layout="wide")


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _claims_df(claims: list[dict[str, Any]]) -> pd.DataFrame:
    if not claims:
        return pd.DataFrame(columns=["ticker", "stance", "confidence", "author", "source", "url", "evidence"])
    df = pd.DataFrame(claims)
    stance_map = {
        "buy": "买入",
        "hold": "持有",
        "sell": "卖出",
        "flat": "空仓",
        "watch": "观察",
    }
    df["stance_cn"] = df["stance"].map(stance_map).fillna(df["stance"])
    df = df[["ticker", "stance_cn", "confidence", "author", "source", "url", "evidence", "extractor"]]
    df = df.rename(columns={"stance_cn": "动作", "confidence": "置信度", "author": "作者", "source": "来源", "url": "链接", "evidence": "证据", "extractor": "抽取器", "ticker": "Ticker"})
    return df.sort_values(by="置信度", ascending=False)


def _posts_df(posts: list[dict[str, Any]]) -> pd.DataFrame:
    if not posts:
        return pd.DataFrame(columns=["source", "author", "title", "text", "url"])
    df = pd.DataFrame(posts)
    return df[["source", "author", "title", "text", "url"]].rename(columns={"source": "来源", "author": "作者", "title": "标题", "text": "正文", "url": "链接"})

config = load_config()
runtime_llm = resolve_llm_config(config.get("llm", {}))
snapshots = load_snapshots()
latest_snapshot = snapshots[-1] if snapshots else None

st.title("📡 社交持仓雷达")
st.caption("自动汇总公开发言里的持仓线索，适合盯单个账号、主题人物或小圈子。")

with st.sidebar:
    st.subheader("监控配置")
    target_name = st.text_input("目标名称", value=config.get("target_name", "Serenity"))
    aliases = st.text_area("别名 / 关键词", value="\n".join(config.get("aliases", [])), height=100)
    x_profiles = st.text_area("X 用户名", value="\n".join(config.get("x_profiles", [])), height=90, placeholder="例如：aleabitoreddit")
    x_status_urls = st.text_area("X 单帖链接", value="\n".join(config.get("x_status_urls", [])), height=90, placeholder="可留空，适合盯重点帖子")
    reddit_users = st.text_area("Reddit 用户名", value="\n".join(config.get("reddit_users", [])), height=90, placeholder="例如：aleabitoreddit")
    web_urls = st.text_area("网页地址", value="\n".join(config.get("web_urls", [])), height=90, placeholder="可放公开文章或个人页")
    search_queries = st.text_area("搜索查询", value="\n".join(config.get("search_queries", [])), height=150)
    post_limit = st.slider("每个源最多抓多少条", min_value=3, max_value=20, value=int(config.get("post_limit", 8)))
    auto_refresh_sec = st.select_slider("页面自动刷新", options=[0, 30, 60, 120, 300, 600], value=0)

    st.subheader("LLM 增强抽取")
    llm_enabled = st.checkbox("启用 DeepSeek / OpenAI 兼容接口", value=config.get("llm", {}).get("enabled", False))
    llm_base_url = st.text_input("Base URL", value=config.get("llm", {}).get("base_url", "https://api.deepseek.com/v1"))
    llm_model = st.text_input("Model", value=config.get("llm", {}).get("model", "deepseek-chat"))
    if runtime_llm.get("api_key"):
        st.caption("已检测到 LLM 密钥：来自 `st.secrets` 或环境变量。")
    else:
        st.caption("未检测到 LLM 密钥。可在 Streamlit Cloud secrets 或环境变量里配置 `DEEPSEEK_API_KEY`。")

    pending_config = {
        "target_name": target_name.strip(),
        "aliases": _split_lines(aliases),
        "x_profiles": _split_lines(x_profiles),
        "x_status_urls": _split_lines(x_status_urls),
        "reddit_users": _split_lines(reddit_users),
        "web_urls": _split_lines(web_urls),
        "search_queries": _split_lines(search_queries),
        "post_limit": post_limit,
        "llm": {
            "enabled": llm_enabled,
            "base_url": llm_base_url.strip(),
            "model": llm_model.strip(),
        },
    }

    if st.button("保存配置", use_container_width=True):
        save_config(pending_config)
        st.success("配置已保存")

    run_now = st.button("立即抓取", type="primary", use_container_width=True)

if run_now:
    with st.spinner("正在抓取并抽取持仓线索..."):
        latest_snapshot = run_pipeline(pending_config)
    st.success("抓取完成")

if auto_refresh_sec and auto_refresh_sec > 0:
    components.html(
        f"""
        <script>
        setTimeout(function() {{
            window.parent.location.reload();
        }}, {int(auto_refresh_sec) * 1000});
        </script>
        """,
        height=0,
    )

if latest_snapshot:
    col1, col2, col3 = st.columns(3)
    col1.metric("最近一次抓到的原文数", latest_snapshot.get("post_count", 0))
    col2.metric("抽取出的持仓线索", latest_snapshot.get("claim_count", 0))
    col3.metric("最近运行时间", latest_snapshot.get("ran_at", "-"))

    if latest_snapshot.get("errors"):
        with st.expander("抓取提示 / 错误", expanded=False):
            for error in latest_snapshot["errors"]:
                st.warning(error)

    st.subheader("持仓线索表")
    claims_df = _claims_df(latest_snapshot.get("claims", []))
    st.dataframe(
        claims_df,
        use_container_width=True,
        column_config={"链接": st.column_config.LinkColumn("链接")},
        hide_index=True,
    )

    st.subheader("原始抓取内容")
    posts_df = _posts_df(latest_snapshot.get("posts", []))
    st.dataframe(
        posts_df,
        use_container_width=True,
        column_config={"链接": st.column_config.LinkColumn("链接")},
        hide_index=True,
    )
else:
    st.info("还没有运行记录。先在左侧保存配置，再点“立即抓取”。")

st.divider()
st.subheader("当前版本建议")
st.markdown(
    """
    - 如果你主要盯 `X`，优先把 `X 用户名` 填上，应用会直接抓公开主页快照。
    - 再配合 `site:x.com/用户名 bought OR "my positions"` 这类搜索词，能补到更多单帖。
    - 如果这个人还有 Reddit、博客、Substack、论坛转发，也可以一起丢进来，命中率会更高。
    - 这一版已经支持页面自动刷新；如果你想后台定时跑，可以直接用命令行脚本接系统定时任务。
    """
)
