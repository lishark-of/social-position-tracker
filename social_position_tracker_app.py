from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from social_tracker.claim_utils import build_author_position_summary, flatten_claims_from_snapshots
from social_tracker.pipeline import run_pipeline
from social_tracker.storage import load_config, load_snapshots, resolve_llm_config, save_config


st.set_page_config(page_title="社交持仓雷达", page_icon="📡", layout="wide")


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _claims_df(claims: list[dict[str, Any]]) -> pd.DataFrame:
    if not claims:
        return pd.DataFrame(
            columns=[
                "canonical_ticker",
                "original_ticker_text",
                "action",
                "claim_type",
                "confidence",
                "position_confidence",
                "author",
                "source",
                "source_url",
                "evidence",
                "language",
            ]
        )
    df = pd.DataFrame(claims)
    df = df[
        [
            "canonical_ticker",
            "original_ticker_text",
            "action",
            "claim_type",
            "confidence",
            "position_confidence",
            "is_position_disclosure",
            "author",
            "source",
            "source_url",
            "evidence",
            "language",
        ]
    ]
    df = df.rename(
        columns={
            "canonical_ticker": "标准Ticker",
            "original_ticker_text": "原文标的",
            "action": "动作",
            "claim_type": "信号类型",
            "confidence": "整体置信度",
            "position_confidence": "仓位置信度",
            "is_position_disclosure": "明确披露",
            "author": "作者",
            "source": "来源",
            "source_url": "链接",
            "evidence": "证据",
            "language": "语言",
        }
    )
    return df.sort_values(by="整体置信度", ascending=False)


def _posts_df(posts: list[dict[str, Any]]) -> pd.DataFrame:
    if not posts:
        return pd.DataFrame(columns=["source", "author", "title", "text", "url"])
    df = pd.DataFrame(posts)
    return df[["source", "author", "title", "text", "url"]].rename(columns={"source": "来源", "author": "作者", "title": "标题", "text": "正文", "url": "链接"})


def _changes_df(changes: list[dict[str, Any]]) -> pd.DataFrame:
    if not changes:
        return pd.DataFrame(
            columns=[
                "canonical_ticker",
                "original_ticker_text",
                "source",
                "author",
                "previous_action",
                "latest_action",
                "change_type",
                "latest_evidence",
                "latest_captured_at",
            ]
        )
    df = pd.DataFrame(changes)
    change_map = {
        "upgraded": "观点升温",
        "downgraded": "观点降温",
        "unchanged": "无明显变化",
        "new": "新增观点",
        "unknown": "无法判断",
    }
    df["change_label"] = df["change_type"].map(change_map).fillna(df["change_type"])
    df = df[
        [
            "canonical_ticker",
            "original_ticker_text",
            "source",
            "author",
            "previous_action",
            "latest_action",
            "change_label",
            "latest_evidence",
            "latest_captured_at",
        ]
    ]
    return df.rename(
        columns={
            "canonical_ticker": "标准Ticker",
            "original_ticker_text": "原文标的",
            "source": "来源",
            "author": "作者",
            "previous_action": "上次观点",
            "latest_action": "最新观点",
            "change_label": "变化方向",
            "latest_evidence": "最新证据",
            "latest_captured_at": "更新时间",
        }
    )


def _author_position_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "author",
                "canonical_ticker",
                "original_ticker_text",
                "latest_action",
                "is_position_disclosure",
                "position_confidence",
                "latest_evidence",
                "source_url",
                "latest_captured_at",
            ]
        )
    df = pd.DataFrame(rows)
    df = df[
        [
            "author",
            "canonical_ticker",
            "original_ticker_text",
            "latest_action",
            "is_position_disclosure",
            "position_confidence",
            "latest_evidence",
            "source_url",
            "latest_captured_at",
        ]
    ]
    return df.rename(
        columns={
            "author": "作者",
            "canonical_ticker": "标准Ticker",
            "original_ticker_text": "原文标的",
            "latest_action": "最新疑似仓位动作",
            "is_position_disclosure": "是否明确披露",
            "position_confidence": "仓位置信度",
            "latest_evidence": "最新证据",
            "source_url": "来源链接",
            "latest_captured_at": "更新时间",
        }
    )


def _select_with_all(label: str, options: list[str], key: str) -> str:
    normalized = [item for item in options if item]
    return st.selectbox(label, ["全部"] + normalized, index=0, key=key)


def _apply_common_filters(
    rows: list[dict[str, Any]],
    author_value: str = "全部",
    ticker_value: str = "全部",
    source_value: str = "全部",
    language_value: str = "全部",
) -> list[dict[str, Any]]:
    filtered = rows
    if author_value != "全部":
        filtered = [row for row in filtered if row.get("author", "") == author_value]
    if ticker_value != "全部":
        filtered = [row for row in filtered if row.get("canonical_ticker", "") == ticker_value]
    if source_value != "全部":
        filtered = [row for row in filtered if row.get("source", "") == source_value]
    if language_value != "全部":
        filtered = [row for row in filtered if row.get("language", "unknown") == language_value]
    return filtered

config = load_config()
runtime_llm = resolve_llm_config(config.get("llm", {}))
snapshots = load_snapshots()
latest_snapshot = snapshots[-1] if snapshots else None
all_claims = flatten_claims_from_snapshots(snapshots, dedupe=True)
author_position_rows = build_author_position_summary(all_claims)
claim_authors = sorted({claim.get("author", "") for claim in all_claims if claim.get("author", "")})
claim_tickers = sorted({claim.get("canonical_ticker", "") for claim in all_claims if claim.get("canonical_ticker", "")})
claim_sources = sorted({claim.get("source", "") for claim in all_claims if claim.get("source", "")})
claim_types = sorted({claim.get("claim_type", "") for claim in all_claims if claim.get("claim_type", "")})
claim_languages = sorted({claim.get("language", "unknown") for claim in all_claims if claim.get("language", "unknown")})
change_types = (
    sorted({item.get("change_type", "") for item in latest_snapshot.get("claim_changes", []) if item.get("change_type", "")})
    if latest_snapshot
    else []
)

st.title("📡 社交持仓雷达")
st.caption("自动汇总公开发言里的持仓线索，适合盯单个账号、主题人物或小圈子。")
st.warning("本工具仅基于公开内容追踪观点和疑似仓位线索，不代表作者真实账户持仓，不构成投资建议。")

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
        snapshots = load_snapshots()
        all_claims = flatten_claims_from_snapshots(snapshots, dedupe=True)
        author_position_rows = build_author_position_summary(all_claims)
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

st.subheader("筛选")
filter_col1, filter_col2, filter_col3 = st.columns(3)
with filter_col1:
    filter_author = _select_with_all("作者", claim_authors, "filter_author")
    filter_ticker = _select_with_all("标准Ticker", claim_tickers, "filter_ticker")
with filter_col2:
    filter_source = _select_with_all("来源", claim_sources, "filter_source")
    filter_claim_type = _select_with_all("信号类型", claim_types, "filter_claim_type")
with filter_col3:
    filter_change_type = _select_with_all("变化类型", change_types, "filter_change_type")
    filter_language = _select_with_all("语言", claim_languages, "filter_language")

position_filter_col1, position_filter_col2 = st.columns(2)
with position_filter_col1:
    position_confidence_threshold = st.slider(
        "仓位置信度最低阈值",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.05,
    )
with position_filter_col2:
    only_explicit_disclosure = st.checkbox("只看明确披露仓位", value=False)

if latest_snapshot:
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("最近一次抓到的原文数", latest_snapshot.get("post_count", 0))
    col2.metric("抽取出的持仓线索", latest_snapshot.get("claim_count", 0))
    col3.metric("新增线索", latest_snapshot.get("new_claim_count", 0))
    col4.metric("重复线索", latest_snapshot.get("duplicate_claim_count", 0))
    col5.metric("观点变化数", latest_snapshot.get("changed_opinion_count", 0))

    st.caption(
        f"position_signal={latest_snapshot.get('position_signal_count', 0)} | "
        f"opinion_signal={latest_snapshot.get('opinion_signal_count', 0)} | "
        f"risk_signal={latest_snapshot.get('risk_signal_count', 0)} | "
        f"最近运行时间={latest_snapshot.get('ran_at', '-')}"
    )

    if latest_snapshot.get("errors"):
        with st.expander("抓取提示 / 错误", expanded=False):
            for error in latest_snapshot["errors"]:
                st.warning(error)

    st.subheader("今日观点变化")
    latest_claim_map = {claim.get("claim_hash", ""): claim for claim in latest_snapshot.get("claims", [])}
    filtered_changes = []
    for change in latest_snapshot.get("claim_changes", []):
        matching_claim = None
        for claim in latest_snapshot.get("claims", []):
            if (
                claim.get("canonical_ticker", "") == change.get("canonical_ticker", "")
                and claim.get("author", "") == change.get("author", "")
                and claim.get("source", "") == change.get("source", "")
                and claim.get("captured_at", "") == change.get("latest_captured_at", "")
                and claim.get("evidence", "") == change.get("latest_evidence", "")
            ):
                matching_claim = claim
                break
        if filter_author != "全部" and change.get("author", "") != filter_author:
            continue
        if filter_ticker != "全部" and change.get("canonical_ticker", "") != filter_ticker:
            continue
        if filter_source != "全部" and change.get("source", "") != filter_source:
            continue
        if filter_change_type != "全部" and change.get("change_type", "") != filter_change_type:
            continue
        if filter_language != "全部":
            change_language = (matching_claim or {}).get("language", "unknown")
            if change_language != filter_language:
                continue
        filtered_changes.append(change)
    changes_df = _changes_df(filtered_changes)
    if changes_df.empty:
        st.info("暂无符合条件的数据，请调整筛选条件或先执行刷新。")
    else:
        st.dataframe(changes_df, use_container_width=True, hide_index=True)

    st.subheader("作者疑似持仓动态")
    st.caption("本模块仅基于作者公开表达推断疑似仓位线索，不代表真实账户持仓。")
    filtered_position_rows = _apply_common_filters(
        author_position_rows,
        author_value=filter_author,
        ticker_value=filter_ticker,
        source_value=filter_source,
        language_value="全部",
    )
    if filter_language != "全部":
        filtered_position_rows = [
            row
            for row in filtered_position_rows
            if next(
                (
                    claim.get("language", "unknown")
                    for claim in all_claims
                    if claim.get("author", "") == row.get("author", "")
                    and claim.get("canonical_ticker", "") == row.get("canonical_ticker", "")
                    and claim.get("captured_at", "") == row.get("latest_captured_at", "")
                ),
                "unknown",
            )
            == filter_language
        ]
    if filter_claim_type != "全部" and filter_claim_type != "position_signal":
        filtered_position_rows = []
    filtered_position_rows = [
        row
        for row in filtered_position_rows
        if float(row.get("position_confidence", 0.0) or 0.0) >= position_confidence_threshold
    ]
    if only_explicit_disclosure:
        filtered_position_rows = [row for row in filtered_position_rows if row.get("is_position_disclosure", False)]
    author_position_df = _author_position_df(filtered_position_rows)
    if author_position_df.empty:
        st.info("暂无符合条件的数据，请调整筛选条件或先执行刷新。")
    else:
        st.dataframe(
            author_position_df,
            use_container_width=True,
            column_config={"来源链接": st.column_config.LinkColumn("来源链接")},
            hide_index=True,
        )

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
    - 本工具只追踪公开表达出来的观点、买卖态度和疑似仓位线索，不等于真实账户持仓。
    - 这一版已经支持页面自动刷新；如果你想后台定时跑，可以直接用命令行脚本接系统定时任务。
    """
)
