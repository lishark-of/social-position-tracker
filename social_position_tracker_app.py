from __future__ import annotations

import re
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from social_tracker.claim_utils import build_author_position_summary, flatten_claims_from_snapshots
from social_tracker.pipeline import run_pipeline
from social_tracker.storage import load_config, load_snapshots, resolve_llm_config, save_config


st.set_page_config(page_title="社交持仓雷达", page_icon="🛰️", layout="wide")


TIME_RANGE_OPTIONS = {
    "最近 24 小时": 1,
    "最近 3 天": 3,
    "最近 7 天": 7,
    "最近 30 天": 30,
    "不限制": None,
}
DEFAULT_PLATFORMS = ["X", "Reddit", "Web/Search"]


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _display_author(value: str) -> str:
    return value if value else "未识别作者"


def _format_bool_zh(value: Any) -> str:
    return "是" if bool(value) else "否"


def _parse_datetime(value: Any) -> pd.Timestamp | None:
    if value in (None, "", "nan"):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"\d{10}(?:\.\d+)?", text):
            return pd.to_datetime(float(text), unit="s", utc=True)
        if re.fullmatch(r"\d{13}", text):
            return pd.to_datetime(float(text), unit="ms", utc=True)
        parsed = pd.to_datetime(text, utc=True, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed
    except Exception:
        return None


def _format_time_value(value: Any, empty_label: str) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return empty_label
    return parsed.tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M")


def _time_sort_key(row: dict[str, Any], preferred: list[str]) -> pd.Timestamp:
    for field in preferred:
        parsed = _parse_datetime(row.get(field, ""))
        if parsed is not None:
            return parsed
    return pd.Timestamp.min.tz_localize("UTC")


def _within_time_range(row: dict[str, Any], time_range_label: str, preferred: list[str]) -> bool:
    days = TIME_RANGE_OPTIONS.get(time_range_label)
    if days is None:
        return True
    now = pd.Timestamp.utcnow()
    cutoff = now - pd.Timedelta(days=days)
    for field in preferred:
        parsed = _parse_datetime(row.get(field, ""))
        if parsed is not None:
            return parsed >= cutoff
    return False


def _extract_handle(user_input: str) -> tuple[str, str]:
    text = (user_input or "").strip()
    if not text:
        return "", ""
    x_match = re.search(r"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,20})", text, flags=re.IGNORECASE)
    if x_match:
        return x_match.group(1), "x"
    reddit_match = re.search(r"(?:https?://)?(?:www\.)?reddit\.com/(?:user|u)/([A-Za-z0-9_\-]+)", text, flags=re.IGNORECASE)
    if reddit_match:
        return reddit_match.group(1), "reddit"
    cleaned = text.lstrip("@").strip()
    if re.fullmatch(r"[A-Za-z0-9_]{1,30}", cleaned):
        return cleaned, "handle"
    return text, "keyword"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = item.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _build_queries(user_input: str, handle: str) -> list[str]:
    identity = handle or user_input.strip().lstrip("@")
    if not identity:
        return []
    queries = [
        f"site:x.com/{identity} bought OR added OR holding OR sold",
        f"site:x.com/{identity} position OR portfolio OR long OR trim",
        f"site:reddit.com {identity} bought added holding sold position",
        f"{identity} stocks portfolio positions holdings",
        f"{identity} 买入 加仓 持有 卖出 清仓",
        f"{identity} 持仓 组合 观点 股票",
        f"{identity} 空仓 观察 减仓",
    ]
    return _unique(queries)


def _build_run_config(
    base_config: dict[str, Any],
    query_input: str,
    platforms: list[str],
    post_limit: int,
    custom_queries: list[str],
    llm_enabled: bool,
    llm_base_url: str,
    llm_model: str,
) -> dict[str, Any]:
    handle, input_kind = _extract_handle(query_input)
    query_input = query_input.strip()
    x_profiles: list[str] = []
    x_status_urls: list[str] = []
    reddit_users: list[str] = []
    web_urls: list[str] = []
    search_queries: list[str] = []

    if "X" in platforms:
        if input_kind in {"x", "handle"} and handle and "/status/" not in query_input:
            x_profiles.append(handle)
        if input_kind == "x" and "/status/" in query_input.lower():
            x_status_urls.append(query_input)
            if handle:
                x_profiles.append(handle)

    if "Reddit" in platforms and handle and input_kind in {"reddit", "handle"}:
        reddit_users.append(handle)

    if "Web/Search" in platforms:
        if query_input.startswith(("http://", "https://")) and input_kind not in {"x", "reddit"}:
            web_urls.append(query_input)
        search_queries.extend(_build_queries(query_input, handle))

    search_queries.extend(custom_queries)

    return {
        "target_name": handle or query_input,
        "aliases": _unique([query_input, handle]),
        "x_profiles": _unique(x_profiles),
        "x_status_urls": _unique(x_status_urls),
        "reddit_users": _unique(reddit_users),
        "web_urls": _unique(web_urls),
        "search_queries": _unique(search_queries),
        "post_limit": post_limit,
        "llm": {
            "enabled": llm_enabled,
            "base_url": llm_base_url.strip(),
            "model": llm_model.strip(),
        },
    }


def _claims_df(claims: list[dict[str, Any]]) -> pd.DataFrame:
    if not claims:
        return pd.DataFrame(
            columns=[
                "抓取时间",
                "原文发布时间",
                "作者",
                "来源",
                "发现来源",
                "标准标的",
                "动作",
                "信号类型",
                "是否明确披露仓位",
                "仓位置信度",
                "整体置信度",
                "原文证据",
                "来源链接",
            ]
        )
    rows = []
    for claim in claims:
        rows.append(
            {
                "抓取时间": _format_time_value(claim.get("captured_at", ""), "抓取时间未知"),
                "原文发布时间": _format_time_value(claim.get("published_at", ""), "原文时间未知"),
                "作者": _display_author(claim.get("author", "")),
                "来源": claim.get("source", ""),
                "发现来源": claim.get("discovery_source", "") or "",
                "标准标的": claim.get("canonical_ticker", ""),
                "动作": claim.get("action", ""),
                "信号类型": claim.get("claim_type", ""),
                "是否明确披露仓位": _format_bool_zh(claim.get("is_position_disclosure", False)),
                "仓位置信度": f"{float(claim.get('position_confidence', 0.0) or 0.0):.2f}",
                "整体置信度": f"{float(claim.get('confidence', 0.0) or 0.0):.2f}",
                "原文证据": claim.get("evidence", ""),
                "来源链接": claim.get("source_url", ""),
                "_sort_time": _time_sort_key(claim, ["captured_at", "published_at"]),
            }
        )
    df = pd.DataFrame(rows).sort_values(by="_sort_time", ascending=False).drop(columns=["_sort_time"])
    return df


def _claims_export_df(claims: list[dict[str, Any]]) -> pd.DataFrame:
    if not claims:
        return pd.DataFrame(
            columns=[
                "来源",
                "发现来源",
                "作者",
                "标准标的",
                "原文标的",
                "动作",
                "信号类型",
                "是否明确披露仓位",
                "仓位置信度",
                "整体置信度",
                "置信度原因",
                "原文证据",
                "来源链接",
                "原文发布时间",
                "抓取时间",
                "语言",
                "去重ID",
            ]
        )
    rows = []
    for claim in claims:
        rows.append(
            {
                "来源": claim.get("source", ""),
                "发现来源": claim.get("discovery_source", "") or "",
                "作者": _display_author(claim.get("author", "")),
                "标准标的": claim.get("canonical_ticker", ""),
                "原文标的": claim.get("original_ticker_text", ""),
                "动作": claim.get("action", ""),
                "信号类型": claim.get("claim_type", ""),
                "是否明确披露仓位": _format_bool_zh(claim.get("is_position_disclosure", False)),
                "仓位置信度": f"{float(claim.get('position_confidence', 0.0) or 0.0):.2f}",
                "整体置信度": f"{float(claim.get('confidence', 0.0) or 0.0):.2f}",
                "置信度原因": claim.get("confidence_reason", ""),
                "原文证据": claim.get("evidence", ""),
                "来源链接": claim.get("source_url", ""),
                "原文发布时间": claim.get("published_at", ""),
                "抓取时间": claim.get("captured_at", ""),
                "语言": claim.get("language", ""),
                "去重ID": claim.get("claim_hash", ""),
            }
        )
    return pd.DataFrame(rows)


def _build_change_rows(latest_snapshot: dict[str, Any], all_claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    latest_claims = latest_snapshot.get("claims", [])
    for change in latest_snapshot.get("claim_changes", []):
        latest_match = next(
            (
                claim
                for claim in latest_claims
                if claim.get("canonical_ticker", "") == change.get("canonical_ticker", "")
                and claim.get("author", "") == change.get("author", "")
                and claim.get("source", "") == change.get("source", "")
                and claim.get("captured_at", "") == change.get("latest_captured_at", "")
                and claim.get("evidence", "") == change.get("latest_evidence", "")
            ),
            {},
        )
        previous_match = next(
            (
                claim
                for claim in all_claims
                if claim.get("canonical_ticker", "") == change.get("canonical_ticker", "")
                and claim.get("author", "") == change.get("author", "")
                and claim.get("source", "") == change.get("source", "")
                and claim.get("captured_at", "") == change.get("previous_captured_at", "")
                and claim.get("evidence", "") == change.get("previous_evidence", "")
            ),
            {},
        )
        rows.append(
            {
                "author": change.get("author", ""),
                "canonical_ticker": change.get("canonical_ticker", ""),
                "original_ticker_text": change.get("original_ticker_text", ""),
                "previous_action": change.get("previous_action", ""),
                "latest_action": change.get("latest_action", ""),
                "change_type": change.get("change_type", "unknown"),
                "previous_time": _format_time_value(
                    previous_match.get("published_at", "") or change.get("previous_captured_at", ""),
                    "未知",
                ),
                "latest_time": _format_time_value(
                    latest_match.get("published_at", "") or change.get("latest_captured_at", ""),
                    "未知",
                ),
                "latest_evidence": change.get("latest_evidence", ""),
                "source_url": latest_match.get("source_url", ""),
                "source": change.get("source", ""),
                "language": latest_match.get("language", "unknown"),
                "_sort_time": _time_sort_key(latest_match or change, ["published_at", "latest_captured_at", "captured_at"]),
            }
        )
    return sorted(rows, key=lambda item: item["_sort_time"], reverse=True)


def _changes_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=["作者", "标准标的", "上次观点", "最新观点", "变化方向", "上次时间", "最新时间", "最新证据", "来源链接"]
        )
    change_map = {
        "upgraded": "升温",
        "downgraded": "降温",
        "unchanged": "无明显变化",
        "new": "新增",
        "unknown": "无法判断",
    }
    formatted = []
    for row in rows:
        formatted.append(
            {
                "作者": _display_author(row.get("author", "")),
                "标准标的": row.get("canonical_ticker", ""),
                "上次观点": row.get("previous_action", "") or "未知",
                "最新观点": row.get("latest_action", "") or "未知",
                "变化方向": change_map.get(row.get("change_type", "unknown"), row.get("change_type", "unknown")),
                "上次时间": row.get("previous_time", "未知"),
                "最新时间": row.get("latest_time", "未知"),
                "最新证据": row.get("latest_evidence", ""),
                "来源链接": row.get("source_url", ""),
                "_sort_time": row.get("_sort_time", pd.Timestamp.min.tz_localize("UTC")),
            }
        )
    return pd.DataFrame(formatted).sort_values(by="_sort_time", ascending=False).drop(columns=["_sort_time"])


def _author_position_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "作者",
                "标准标的",
                "最新动作",
                "仓位置信度",
                "最新证据",
                "原文发布时间",
                "抓取时间",
                "来源",
                "发现来源",
                "来源链接",
            ]
        )
    formatted = []
    for row in rows:
        formatted.append(
            {
                "作者": _display_author(row.get("author", "")),
                "标准标的": row.get("canonical_ticker", ""),
                "最新动作": row.get("latest_action", ""),
                "仓位置信度": f"{float(row.get('position_confidence', 0.0) or 0.0):.2f}",
                "最新证据": row.get("latest_evidence", ""),
                "原文发布时间": _format_time_value(row.get("latest_published_at", ""), "原文时间未知"),
                "抓取时间": _format_time_value(row.get("latest_captured_at", ""), "抓取时间未知"),
                "来源": row.get("source", ""),
                "发现来源": row.get("discovery_source", "") or "",
                "来源链接": row.get("source_url", ""),
                "_position_conf": float(row.get("position_confidence", 0.0) or 0.0),
                "_sort_time": _time_sort_key(row, ["latest_published_at", "latest_captured_at"]),
            }
        )
    return (
        pd.DataFrame(formatted)
        .sort_values(by=["_position_conf", "_sort_time"], ascending=[False, False])
        .drop(columns=["_position_conf", "_sort_time"])
    )


def _select_with_all(label: str, options: list[str], key: str) -> str:
    normalized = [item for item in sorted(options) if item]
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


def _filter_by_time_range(rows: list[dict[str, Any]], time_range_label: str, preferred_fields: list[str]) -> list[dict[str, Any]]:
    return [row for row in rows if _within_time_range(row, time_range_label, preferred_fields)]


config = load_config()
runtime_llm = resolve_llm_config(config.get("llm", {}))
snapshots = load_snapshots()
latest_snapshot = snapshots[-1] if snapshots else None
all_claims = flatten_claims_from_snapshots(snapshots, dedupe=True)
author_position_rows = build_author_position_summary(all_claims)

default_query = config.get("x_profiles", [""])[0] if config.get("x_profiles") else config.get("target_name", "")

st.title("🛰️ 社交持仓雷达")
st.caption("输入一个作者主页或关键词，自动追踪其公开社媒观点、疑似持仓动作和最新变化。")
st.warning("本工具仅基于公开内容追踪观点和疑似仓位线索，不代表作者真实账户持仓，不构成投资建议。")

with st.container(border=True):
    st.subheader("🔎 查询作者/账号")
    with st.form("author_query_form", clear_on_submit=False):
        query_input = st.text_input(
            "作者主页或账号关键词",
            value=st.session_state.get("query_input", default_query),
            placeholder="例如：https://x.com/aleabitoreddit 或 aleabitoreddit",
        )
        form_col1, form_col2 = st.columns([1.2, 1])
        with form_col1:
            selected_platforms = st.multiselect("可选平台", DEFAULT_PLATFORMS, default=st.session_state.get("selected_platforms", DEFAULT_PLATFORMS))
            selected_time_range = st.selectbox(
                "时间范围",
                list(TIME_RANGE_OPTIONS.keys()),
                index=list(TIME_RANGE_OPTIONS.keys()).index(st.session_state.get("selected_time_range", "最近 7 天")),
            )
        with form_col2:
            per_platform_limit = st.slider("每个平台最多抓取条数", min_value=5, max_value=100, value=st.session_state.get("per_platform_limit", 20), step=5)
            run_now = st.form_submit_button("立即追踪", type="primary", use_container_width=True)

st.session_state["query_input"] = query_input
st.session_state["selected_platforms"] = selected_platforms
st.session_state["selected_time_range"] = selected_time_range
st.session_state["per_platform_limit"] = per_platform_limit

with st.sidebar:
    st.subheader("页面设置")
    auto_refresh_enabled = st.toggle("自动刷新", value=False)
    auto_refresh_sec = st.select_slider("自动刷新间隔", options=[30, 60, 120, 300, 600], value=60, disabled=not auto_refresh_enabled)
    with st.expander("高级设置（可选）", expanded=False):
        custom_search_queries = st.text_area(
            "自定义搜索 query 列表",
            value="\n".join(config.get("search_queries", [])),
            height=140,
        )
        llm_enabled = st.checkbox("启用 LLM 增强抽取", value=config.get("llm", {}).get("enabled", False))
        llm_base_url = st.text_input("Base URL", value=config.get("llm", {}).get("base_url", "https://api.deepseek.com/v1"))
        llm_model = st.text_input("Model", value=config.get("llm", {}).get("model", "deepseek-chat"))
        if runtime_llm.get("api_key"):
            st.caption("已检测到 LLM 密钥：来自 `st.secrets` 或环境变量。")
        else:
            st.caption("未检测到 LLM 密钥。可在 Streamlit Cloud secrets 或环境变量里配置 `DEEPSEEK_API_KEY`。")
        if st.button("保存高级设置", use_container_width=True):
            advanced_config = {
                **config,
                "search_queries": _split_lines(custom_search_queries),
                "llm": {
                    "enabled": llm_enabled,
                    "base_url": llm_base_url.strip(),
                    "model": llm_model.strip(),
                },
            }
            save_config(advanced_config)
            st.success("高级设置已保存")

if run_now and query_input.strip():
    generated_config = _build_run_config(
        base_config=config,
        query_input=query_input,
        platforms=selected_platforms,
        post_limit=per_platform_limit,
        custom_queries=_split_lines(custom_search_queries),
        llm_enabled=llm_enabled,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
    )
    with st.spinner("正在追踪这个作者最近的公开表达..."):
        latest_snapshot = run_pipeline(generated_config)
        snapshots = load_snapshots()
        all_claims = flatten_claims_from_snapshots(snapshots, dedupe=True)
        author_position_rows = build_author_position_summary(all_claims)
    st.success("追踪完成")

if auto_refresh_enabled:
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

claim_authors = sorted({claim.get("author", "") for claim in all_claims if claim.get("author", "")})
claim_tickers = sorted({claim.get("canonical_ticker", "") for claim in all_claims if claim.get("canonical_ticker", "")})
claim_sources = sorted({claim.get("source", "") for claim in all_claims if claim.get("source", "")})
claim_types = sorted({claim.get("claim_type", "") for claim in all_claims if claim.get("claim_type", "")})
claim_languages = sorted({claim.get("language", "unknown") for claim in all_claims if claim.get("language", "unknown")})

change_rows = _build_change_rows(latest_snapshot, all_claims) if latest_snapshot else []
change_types = sorted({item.get("change_type", "") for item in change_rows if item.get("change_type", "")})

with st.expander("筛选条件", expanded=False):
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        filter_author = _select_with_all("作者", claim_authors, "filter_author")
        filter_ticker = _select_with_all("标准Ticker", claim_tickers, "filter_ticker")
        filter_source = _select_with_all("来源", claim_sources, "filter_source")
    with filter_col2:
        filter_claim_type = _select_with_all("信号类型", claim_types, "filter_claim_type")
        filter_change_type = _select_with_all("变化类型", change_types, "filter_change_type")
        filter_language = _select_with_all("语言", claim_languages, "filter_language")
    with filter_col3:
        position_confidence_threshold = st.slider("仓位置信度最低阈值", min_value=0.0, max_value=1.0, value=0.5, step=0.05)
        only_explicit_disclosure = st.checkbox("只看明确披露仓位", value=False)
        show_all_claims = st.checkbox("显示全部", value=False)

if latest_snapshot:
    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("最新抓取时间", _format_time_value(latest_snapshot.get("ran_at", ""), "暂无"))
    metric_col2.metric("抓到内容数", latest_snapshot.get("post_count", 0))
    metric_col3.metric("识别线索数", latest_snapshot.get("claim_count", 0))
    metric_col4.metric("疑似持仓动作数", latest_snapshot.get("position_signal_count", 0))

    st.caption(
        f"post_count={latest_snapshot.get('post_count', 0)} | "
        f"claim_count={latest_snapshot.get('claim_count', 0)} | "
        f"new_claim_count={latest_snapshot.get('new_claim_count', 0)} | "
        f"duplicate_claim_count={latest_snapshot.get('duplicate_claim_count', 0)} | "
        f"position_signal_count={latest_snapshot.get('position_signal_count', 0)} | "
        f"opinion_signal_count={latest_snapshot.get('opinion_signal_count', 0)} | "
        f"risk_signal_count={latest_snapshot.get('risk_signal_count', 0)} | "
        f"error_count={latest_snapshot.get('error_count', 0)}"
    )

    if latest_snapshot.get("errors"):
        with st.expander("抓取提示 / 错误", expanded=False):
            for error in latest_snapshot["errors"]:
                st.warning(error)

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
    filtered_position_rows = _filter_by_time_range(filtered_position_rows, selected_time_range, ["latest_published_at", "latest_captured_at"])
    filtered_position_rows = [
        row
        for row in filtered_position_rows
        if float(row.get("position_confidence", 0.0) or 0.0) >= position_confidence_threshold
    ]
    if only_explicit_disclosure:
        filtered_position_rows = [row for row in filtered_position_rows if row.get("is_position_disclosure", False)]

    st.subheader("📌 作者疑似持仓动态")
    st.caption("仅展示作者公开表达中带有明确买入、持有、卖出、减仓、清仓、空仓等仓位线索的内容。")
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

    filtered_changes = []
    for row in change_rows:
        if filter_author != "全部" and row.get("author", "") != filter_author:
            continue
        if filter_ticker != "全部" and row.get("canonical_ticker", "") != filter_ticker:
            continue
        if filter_source != "全部" and row.get("source", "") != filter_source:
            continue
        if filter_change_type != "全部" and row.get("change_type", "") != filter_change_type:
            continue
        if filter_language != "全部" and row.get("language", "unknown") != filter_language:
            continue
        if not _within_time_range(row, selected_time_range, ["latest_time"]):
            continue
        filtered_changes.append(row)

    st.subheader("📈 观点变化雷达")
    changes_df = _changes_df(filtered_changes)
    if changes_df.empty:
        st.info("暂无符合条件的数据，请调整筛选条件或先执行刷新。")
    else:
        st.dataframe(
            changes_df,
            use_container_width=True,
            column_config={"来源链接": st.column_config.LinkColumn("来源链接")},
            hide_index=True,
        )

    filtered_claims = _apply_common_filters(
        latest_snapshot.get("claims", []),
        author_value=filter_author,
        ticker_value=filter_ticker,
        source_value=filter_source,
        language_value=filter_language,
    )
    if filter_claim_type != "全部":
        filtered_claims = [claim for claim in filtered_claims if claim.get("claim_type", "") == filter_claim_type]
    filtered_claims = _filter_by_time_range(filtered_claims, selected_time_range, ["published_at", "captured_at"])
    if only_explicit_disclosure:
        filtered_claims = [claim for claim in filtered_claims if claim.get("is_position_disclosure", False)]
    filtered_claims = [
        claim
        for claim in filtered_claims
        if float(claim.get("position_confidence", 0.0) or 0.0) >= position_confidence_threshold
        or claim.get("claim_type", "") != "position_signal"
    ]
    filtered_claims = sorted(
        filtered_claims,
        key=lambda item: _time_sort_key(item, ["captured_at", "published_at"]),
        reverse=True,
    )
    visible_claims = filtered_claims if show_all_claims else filtered_claims[:50]

    st.subheader("🧾 最新公开线索")
    st.download_button(
        "导出当前线索 CSV",
        data=_claims_export_df(filtered_claims).to_csv(index=False).encode("utf-8-sig"),
        file_name="social_position_tracker_claims.csv",
        mime="text/csv",
        use_container_width=False,
    )
    claims_df = _claims_df(visible_claims)
    if claims_df.empty:
        st.info("暂无符合条件的数据，请调整筛选条件或先执行刷新。")
    else:
        st.dataframe(
            claims_df,
            use_container_width=True,
            column_config={"来源链接": st.column_config.LinkColumn("来源链接")},
            hide_index=True,
        )

    with st.expander("原始抓取内容", expanded=False):
        posts_df = pd.DataFrame(latest_snapshot.get("posts", []))
        if posts_df.empty:
            st.info("本次没有可展示的原始抓取内容。")
        else:
            display_posts = posts_df[["source", "author", "title", "text", "url"]].rename(
                columns={"source": "来源", "author": "作者", "title": "标题", "text": "正文", "url": "链接"}
            )
            display_posts["作者"] = display_posts["作者"].apply(_display_author)
            st.dataframe(
                display_posts,
                use_container_width=True,
                column_config={"链接": st.column_config.LinkColumn("链接")},
                hide_index=True,
            )
else:
    st.info("暂无数据，请先输入作者并点击“立即追踪”。")
