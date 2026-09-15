import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import psycopg2
import psycopg2.extras
import streamlit as st

# ==================== إعداد الصفحة ====================
st.set_page_config(
    page_title="لوحة تحليلات التداول",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== جلب الأسرار والاتصال ====================
# يقرأ Streamlit الأسرار تلقائياً من st.secrets أو متغيرات البيئة
DATABASE_URL = st.secrets.get("DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
DB_CA_CERT_PEM = st.secrets.get("DB_CA_CERT_PEM", os.getenv("DB_CA_CERT_PEM", "")).strip()
AUTO_ANALYSIS_INTERVAL_MINUTES = int(st.secrets.get("AUTO_ANALYSIS_INTERVAL_MINUTES", "10"))

_CA_CERT_PATH: Optional[str] = None
if DB_CA_CERT_PEM:
    _ca_file = tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False)
    _ca_file.write(DB_CA_CERT_PEM)
    _ca_file.close()
    _CA_CERT_PATH = _ca_file.name


def get_conn():
    if not DATABASE_URL:
        st.error("⚠️ لم يتم ضبط DATABASE_URL في Streamlit Secrets.")
        st.stop()
    kwargs: Dict[str, Any] = {"dsn": DATABASE_URL, "connect_timeout": 8}
    if _CA_CERT_PATH:
        kwargs["sslmode"] = "verify-full"
        kwargs["sslrootcert"] = _CA_CERT_PATH
    else:
        kwargs["sslmode"] = "require"
    return psycopg2.connect(**kwargs)


def run_query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        st.error(f"خطأ في قاعدة البيانات: {e}")
        return []


# ==================== دوال جلب البيانات ====================

def get_known_symbols() -> List[str]:
    try:
        rows = run_query(
            """
            SELECT DISTINCT symbol FROM technical_snapshots
            UNION
            SELECT DISTINCT unnest(string_to_array(symbols, ',')) FROM active_watches
            ORDER BY 1
            """
        )
        symbols = sorted({r["symbol"] for r in rows if r["symbol"]})
        return symbols if symbols else ["EURUSD", "XAUUSD", "BTCUSD"]
    except Exception:
        return ["EURUSD", "XAUUSD", "BTCUSD"]


def get_known_timeframes() -> List[str]:
    try:
        rows = run_query("SELECT DISTINCT timeframe FROM technical_snapshots ORDER BY 1")
        tf = [r["timeframe"] for r in rows]
        return tf if tf else ["H1", "H4", "M15", "D1"]
    except Exception:
        return ["H1", "H4", "M15", "D1"]


def fetch_system_status() -> Dict[str, Any]:
    status: Dict[str, Any] = {"db_ok": False}
    try:
        latest_tech = run_query("SELECT MAX(created_at) AS ts FROM technical_snapshots")
        latest_report = run_query("SELECT MAX(created_at) AS ts FROM ai_reports")
        watches_count = run_query("SELECT count(*) AS c FROM active_watches")
        snapshots_count = run_query("SELECT count(*) AS c FROM technical_snapshots")

        status["db_ok"] = True
        status["last_technical_update"] = latest_tech[0]["ts"] if latest_tech else None
        status["last_report_update"] = latest_report[0]["ts"] if latest_report else None
        status["active_watches_count"] = watches_count[0]["c"] if watches_count else 0
        status["snapshots_count"] = snapshots_count[0]["c"] if snapshots_count else 0

        if status["last_technical_update"]:
            age_min = (datetime.now(timezone.utc) - status["last_technical_update"]).total_seconds() / 60
            status["pipeline_fresh"] = age_min < (AUTO_ANALYSIS_INTERVAL_MINUTES * 1.5)
            status["last_technical_age_min"] = round(age_min, 1)
        else:
            status["pipeline_fresh"] = False
            status["last_technical_age_min"] = None
    except Exception as e:
        status["error"] = str(e)
    return status


def parse_quick_signal_blocks(report_text: str) -> List[Dict[str, str]]:
    blocks = re.split(r"\n\s*\n", report_text.strip())
    results = []
    for block in blocks:
        header_match = re.search(r"(🟢|🔴|⚪)\s*([A-Za-z0-9]+)\s*—\s*(.+)", block)
        if not header_match:
            continue
        emoji, symbol, direction = header_match.groups()
        fields = {"entry": "-", "sl": "-", "tp1": "-", "tp2": "-", "rr": "-"}
        for label, key in [("الدخول", "entry"), ("SL", "sl"), ("TP1", "tp1"), ("TP2", "tp2"), ("R:R", "rr")]:
            m = re.search(rf"{re.escape(label)}\s*:\s*([^\n]+)", block)
            if m:
                fields[key] = m.group(1).strip()
        results.append({
            "emoji": emoji,
            "symbol": symbol,
            "direction": direction.strip(),
            **fields,
        })
    return results


def fetch_latest_signal_cards() -> List[Dict[str, str]]:
    rows = run_query(
        """
        SELECT DISTINCT ON (symbols_key) symbols_key, report_text, created_at
        FROM ai_reports
        WHERE analysis_type = 'quick_signals'
        ORDER BY symbols_key, created_at DESC
        """
    )
    cards: List[Dict[str, str]] = []
    seen_symbols = set()
    for row in rows:
        for card in parse_quick_signal_blocks(row["report_text"]):
            if card["symbol"] in seen_symbols:
                continue
            seen_symbols.add(card["symbol"])
            card["updated_at"] = row["created_at"].strftime("%Y-%m-%d %H:%M") if row["created_at"] else "-"
            cards.append(card)
    return cards


def fetch_comparison_table(timeframe: str) -> pd.DataFrame:
    rows = run_query(
        """
        SELECT DISTINCT ON (symbol) symbol, last_price, rsi_14, ema_20, ema_50, atr_14, created_at
        FROM technical_snapshots
        WHERE timeframe = %s
        ORDER BY symbol, created_at DESC
        """,
        (timeframe,)
    )
    if not rows:
        return pd.DataFrame(columns=["الزوج", "السعر", "RSI(14)", "EMA(20)", "EMA(50)", "ATR(14)", "آخر تحديث"])
    df = pd.DataFrame(rows)
    return df.rename(columns={
        "symbol": "الزوج", "last_price": "السعر", "rsi_14": "RSI(14)",
        "ema_20": "EMA(20)", "ema_50": "EMA(50)", "atr_14": "ATR(14)", "created_at": "آخر تحديث"
    })


def fetch_indicator_history(symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    rows = run_query(
        """
        SELECT last_price, rsi_14, ema_20, ema_50, created_at
        FROM technical_snapshots
        WHERE symbol = %s AND timeframe = %s
        ORDER BY created_at ASC
        LIMIT %s
        """,
        (symbol, timeframe, limit)
    )
    return pd.DataFrame(rows)


def fetch_price_with_signal_points(symbol: str, timeframe: str, limit: int = 300) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    price_df = fetch_indicator_history(symbol, timeframe, limit)
    signal_rows = run_query(
        """
        SELECT report_text, created_at
        FROM ai_reports
        WHERE analysis_type = 'quick_signals' AND symbols LIKE %s
        ORDER BY created_at ASC
        """,
        (f"%{symbol}%",)
    )

    points = []
    for row in signal_rows:
        for card in parse_quick_signal_blocks(row["report_text"]):
            if card["symbol"] != symbol:
                continue
            if not price_df.empty:
                nearest_idx = (price_df["created_at"] - row["created_at"]).abs().idxmin()
                nearest_row = price_df.loc[nearest_idx]
                points.append({
                    "x": row["created_at"],
                    "y": float(nearest_row["last_price"]),
                    "emoji": card["emoji"],
                    "direction": card["direction"],
                })
    return price_df, points


# ==================== واجهة المستخدم ====================

st.title("📈 لوحة العرض والتحليل الفني (Read-Only)")
st.caption("تستعرض البيانات والتحليلات المخزنة في Aiven مجاناً وبأداء حي.")

SYMBOLS = get_known_symbols()
TIMEFRAMES = get_known_timeframes()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🖥️ حالة النظام",
    "🎯 التوصيات الحية",
    "📊 مقارنة الأزواج",
    "📈 تطور المؤشرات",
    "💰 السعر مع نقاط التوصيات",
    "💬 آخر تحليل مخزن"
])

# ----- Tab 1: حالة النظام -----
with tab1:
    st.subheader("مرآة حالة تدفق البيانات والنظام")
    status = fetch_system_status()
    if status.get("db_ok"):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("قاعدة البيانات Aiven", "متصلة 🟢")
        freshness = "حديثة 🟢" if status.get("pipeline_fresh") else "متأخرة 🔴"
        col2.metric("حالة تدفق البيانات", freshness)
        col3.metric("عمر آخر تحديث", f"{status.get('last_technical_age_min', '-')} دقيقة")
        col4.metric("إجمالي اللقطات الفنية", status.get("snapshots_count", 0))
    else:
        st.error("تعذر الاتصال بقاعدة البيانات.")

# ----- Tab 2: التوصيات الحية -----
with tab2:
    st.subheader("آخر بطاقات توصيات التداول (Quick Signals)")
    cards = fetch_latest_signal_cards()
    if cards:
        cols = st.columns(3)
        for idx, c in enumerate(cards):
            with cols[idx % 3]:
                color = "#2ecc71" if c["emoji"] == "🟢" else "#e74c3c" if c["emoji"] == "🔴" else "#95a5a6"
                st.markdown(
                    f"""
                    <div style="border: 2px solid {color}; padding: 15px; border-radius: 10px; background-color: #111; margin-bottom: 10px;">
                        <h3 style="margin:0; color:{color};">{c['emoji']} {c['symbol']} — {c['direction']}</h3>
                        <hr style="margin: 8px 0;">
                        <p style="margin:3px 0;"><b>الدخول:</b> {c['entry']}</p>
                        <p style="margin:3px 0;"><b>وقف الخسارة (SL):</b> {c['sl']}</p>
                        <p style="margin:3px 0;"><b>أهداف الربح:</b> {c['tp1']} / {c['tp2']}</p>
                        <p style="margin:3px 0;"><b>مخاطرة/عائد:</b> {c['rr']}</p>
                        <small style="color: #777;">التحديث: {c['updated_at']}</small>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
    else:
        st.info("لا توجد إشارات مخزنة متوفرة.")

# ----- Tab 3: مقارنة الأزواج -----
with tab3:
    st.subheader("مقارنة أداء الأزواج المتعددة جنبًا إلى جنب")
    selected_tf = st.selectbox("اختر الإطار الزمني للمقارنة:", TIMEFRAMES, key="comp_tf")
    df_comp = fetch_comparison_table(selected_tf)
    if not df_comp.empty:
        st.dataframe(df_comp, use_container_width=True)
        fig_comp = go.Figure()
        fig_comp.add_trace(go.Bar(x=df_comp["الزوج"], y=df_comp["RSI(14)"], marker_color="#3498db", name="RSI"))
        fig_comp.update_layout(title=f"مقارنة RSI بين الأزواج ({selected_tf})", template="plotly_dark", height=400)
        st.plotly_chart(fig_comp, use_container_width=True)

# ----- Tab 4: تطور المؤشرات -----
with tab4:
    st.subheader("رسم بياني تفاعلي لتطور RSI/EMA عبر الوقت")
    col_a, col_b = st.columns(2)
    s_sym = col_a.selectbox("اختر الزوج:", SYMBOLS, key="ind_sym")
    s_tf = col_b.selectbox("اختر الإطار الزمني:", TIMEFRAMES, key="ind_tf")
    df_ind = fetch_indicator_history(s_sym, s_tf)
    if not df_ind.empty:
        fig_ind = go.Figure()
        fig_ind.add_trace(go.Scatter(x=df_ind["created_at"], y=df_ind["rsi_14"], name="RSI(14)", yaxis="y1", line=dict(color="#f1c40f")))
        fig_ind.add_trace(go.Scatter(x=df_ind["created_at"], y=df_ind["ema_20"], name="EMA(20)", yaxis="y2", line=dict(color="#3498db")))
        fig_ind.add_trace(go.Scatter(x=df_ind["created_at"], y=df_ind["ema_50"], name="EMA(50)", yaxis="y2", line=dict(color="#9b59b6")))
        fig_ind.update_layout(
            title=f"تطور المؤشرات الفنية لـ {s_sym} [{s_tf}]",
            template="plotly_dark", height=480,
            yaxis=dict(title="RSI", range=[0, 100], side="left"),
            yaxis2=dict(title="EMA", overlaying="y", side="right"),
        )
        st.plotly_chart(fig_ind, use_container_width=True)

# ----- Tab 5: السعر مع التوصيات -----
with tab5:
    st.subheader("تطور السعر مع نقاط التوصيات الصادرة")
    col_x, col_y = st.columns(2)
    p_sym = col_x.selectbox("اختر الزوج:", SYMBOLS, key="price_sym")
    p_tf = col_y.selectbox("اختر الإطار الزمني:", TIMEFRAMES, key="price_tf")
    price_df, points = fetch_price_with_signal_points(p_sym, p_tf)
    if not price_df.empty:
        fig_price = go.Figure()
        fig_price.add_trace(go.Scatter(x=price_df["created_at"], y=price_df["last_price"], name="السعر", line=dict(color="#ecf0f1")))
        color_map = {"🟢": "#2ecc71", "🔴": "#e74c3c", "⚪": "#95a5a6"}
        for emoji, label in [("🟢", "شراء"), ("🔴", "بيع"), ("⚪", "حياد")]:
            pts = [p for p in points if p["emoji"] == emoji]
            if pts:
                fig_price.add_trace(go.Scatter(
                    x=[p["x"] for p in pts], y=[p["y"] for p in pts],
                    mode="markers", name=label,
                    marker=dict(color=color_map[emoji], size=12, symbol="circle")
                ))
        fig_price.update_layout(title=f"السعر مطبقاً بنقاط التوصيات التاريخية لـ {p_sym}", template="plotly_dark", height=500)
        st.plotly_chart(fig_price, use_container_width=True)

# ----- Tab 6: الاستعلام عن التحليل -----
with tab6:
    st.subheader("استعلام عن آخر تحليل AI مخزن")
    q_type = st.selectbox("نوع التحليل:", ["full", "quick_signals", "forex_factory", "finnhub"])
    q_symbol = st.text_input("رمز الزوج (مثل XAUUSD, EURUSD):", value="XAUUSD")
    if st.button("عرض التقرير المخزن"):
        rows = run_query(
            "SELECT report_text, created_at FROM ai_reports WHERE analysis_type = %s AND symbols LIKE %s ORDER BY created_at DESC LIMIT 1",
            (q_type, f"%{q_symbol}%")
        )
        if rows:
            st.markdown(f"**تاريخ التقرير:** {rows[0]['created_at']}")
            st.markdown(rows[0]["report_text"])
        else:
            st.info("لا يوجد تحليل مخزن لهذا الزوج حالياً.")