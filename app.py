import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import psycopg2
import psycopg2.extras
import streamlit as st

# ==================== 1. إعداد الصفحة والتصميم الخاص (Custom CSS) ====================
st.set_page_config(
    page_title="Analytics Dashboard | Pro Trading",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# حقن Custom CSS لتحسين المظهر بالكامل
st.markdown("""
    <style>
    /* خلفية التطبيق العامة */
    .stApp {
        background-color: #0b0e11;
        color: #eaecef;
    }
    
    /* اخفاء القوائم الهامشية والتذييل الافتراضي */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* تصميم التبويبات (Tabs) */
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        background-color: #181a20;
        padding: 8px;
        border-radius: 12px;
        border: 1px solid #2b313a;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        color: #848e9c;
        font-weight: 600;
        padding: 8px 16px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #2b313a !important;
        color: #f0b90b !important;
    }

    /* تصميم بطاقات المؤشرات (Metric Cards) */
    .metric-card {
        background: linear-gradient(135deg, #181a20 0%, #1e2329 100%);
        border: 1px solid #2b313a;
        border-radius: 12px;
        padding: 18px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        border-color: #f0b90b;
    }
    .metric-title {
        font-size: 13px;
        color: #848e9c;
        margin-bottom: 6px;
    }
    .metric-value {
        font-size: 22px;
        font-weight: 700;
        color: #f0b90b;
    }

    /* تصميم بطاقات التوصيات (Glassmorphism Cards) */
    .signal-card {
        background: rgba(30, 35, 41, 0.7);
        backdrop-filter: blur(10px);
        border-radius: 14px;
        padding: 20px;
        margin-bottom: 15px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
    }
    .buy-border { border: 1px solid #0ecb81; border-right: 6px solid #0ecb81; }
    .sell-border { border: 1px solid #f6465d; border-right: 6px solid #f6465d; }
    .neutral-border { border: 1px solid #848e9c; border-right: 6px solid #848e9c; }

    /* تحسين خيارات القوائم */
    .stSelectbox div[data-baseweb="select"] {
        background-color: #181a20;
        border-color: #2b313a;
        color: #eaecef;
        border-radius: 8px;
    }
    </style>
""", unsafe_allow_html=True)


# ==================== 2. الاتصال وجلب البيانات ====================
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
        st.error("⚠️ DATABASE_URL غير مضبوط في Secrets.")
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


# ==================== 3. الهيكل الرئيسي للواجهة ====================

# الهيدر الاحترافي
st.markdown("""
    <div style="display:flex; justify-content:space-between; align-items:center; padding:10px 0 25px 0;">
        <div>
            <h1 style="margin:0; font-size:28px; font-weight:800; color:#ffffff;">⚡ TRADING ANALYTICS PRO</h1>
            <p style="margin:0; color:#848e9c; font-size:14px;">نظام المراقبة والتحليل المباشر (Aiven Read-Only Sync)</p>
        </div>
    </div>
""", unsafe_allow_html=True)

SYMBOLS = get_known_symbols()
TIMEFRAMES = get_known_timeframes()

# شريط الحالات العلوي (Top Header Metrics)
status = fetch_system_status()
if status.get("db_ok"):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div class="metric-card"><div class="metric-title">حالة قاعدة البيانات</div><div class="metric-value" style="color:#0ecb81;">متصلة 🟢</div></div>', unsafe_allow_html=True)
    with c2:
        fresh_color = "#0ecb81" if status.get("pipeline_fresh") else "#f6465d"
        fresh_text = "مباشر ⚡" if status.get("pipeline_fresh") else "متأخر ⚠️"
        st.markdown(f'<div class="metric-card"><div class="metric-title">تدفق البيانات</div><div class="metric-value" style="color:{fresh_color};">{fresh_text}</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><div class="metric-title">عمر أحدث لقطة</div><div class="metric-value">{status.get("last_technical_age_min", "-")} دقيقة</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="metric-card"><div class="metric-title">الأزواج المراقبة</div><div class="metric-value">{status.get("active_watches_count", 0)} أزواج</div></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# التبويبات الرسمية
tab_signals, tab_charts, tab_compare, tab_ai = st.tabs([
    "🎯 التوصيات الحية",
    "📈 الرسم البياني المدمج",
    "📊 مقارنة الأزواج",
    "🤖 تقارير AI المخزنة"
])

# ----- TAB 1: التوصيات الحية (Signal Cards) -----
with tab_signals:
    st.subheader("آخر إشارات التداول المولدّة")
    cards = fetch_latest_signal_cards()
    if cards:
        cols = st.columns(3)
        for idx, c in enumerate(cards):
            with cols[idx % 3]:
                card_class = "buy-border" if c["emoji"] == "🟢" else "sell-border" if c["emoji"] == "🔴" else "neutral-border"
                color_code = "#0ecb81" if c["emoji"] == "🟢" else "#f6465d" if c["emoji"] == "🔴" else "#848e9c"
                
                st.markdown(
                    f"""
                    <div class="signal-card {card_class}">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h3 style="margin:0; color:{color_code}; font-size:20px;">{c['emoji']} {c['symbol']}</h3>
                            <span style="background:{color_code}22; color:{color_code}; padding:4px 10px; border-radius:6px; font-weight:bold; font-size:12px;">{c['direction']}</span>
                        </div>
                        <hr style="border-color:#2b313a; margin:12px 0;">
                        <div style="font-size:14px; line-height:1.8;">
                            <div><b>سعر الدخول:</b> <span style="color:#ffffff;">{c['entry']}</span></div>
                            <div><b>وقف الخسارة (SL):</b> <span style="color:#f6465d;">{c['sl']}</span></div>
                            <div><b>الاهداف (TP):</b> <span style="color:#0ecb81;">{c['tp1']}</span> / <span style="color:#0ecb81;">{c['tp2']}</span></div>
                            <div><b>المخاطرة/العائد:</b> <span style="color:#f0b90b;">{c['rr']}</span></div>
                        </div>
                        <div style="margin-top:12px; font-size:11px; color:#848e9c; text-align:left;">⏱️ {c['updated_at']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
    else:
        st.info("لا توجد إشارات حية مخزنة حالياً.")

# ----- TAB 2: الشارت المدمج الاحترافي (Combined Chart) -----
with tab_charts:
    st.subheader("التحليل الفني الشامل وحركة السعر")
    col_a, col_b = st.columns([1, 1])
    s_sym = col_a.selectbox("اختر الزوج:", SYMBOLS, key="ch_sym")
    s_tf = col_b.selectbox("اختر الإطار الزمني:", TIMEFRAMES, key="ch_tf")
    
    df_chart = fetch_indicator_history(s_sym, s_tf)
    if not df_chart.empty:
        # إنشاء شارت مدمج بمحورين رأسيين (Subplots)
        fig = make_subplots(
            rows=2, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.05, 
            row_heights=[0.7, 0.3],
            subplot_titles=(f"سعر {s_sym} ومتوسطات EMA", "مؤشر القوة النسبية RSI(14)")
        )

        # 1. رسم حركة السعر ومتوسطات EMA
        fig.add_trace(go.Scatter(x=df_chart["created_at"], y=df_chart["last_price"], name="السعر", line=dict(color="#ffffff", width=2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_chart["created_at"], y=df_chart["ema_20"], name="EMA 20", line=dict(color="#f0b90b", width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_chart["created_at"], y=df_chart["ema_50"], name="EMA 50", line=dict(color="#e040fb", width=1.5)), row=1, col=1)

        # 2. رسم مؤشر RSI
        fig.add_trace(go.Scatter(x=df_chart["created_at"], y=df_chart["rsi_14"], name="RSI", line=dict(color="#29b6f6", width=1.5)), row=2, col=1)
        
        # خطوط التشبع الشرائي والبيعي للـ RSI
        fig.add_hline(y=70, row=2, col=1, line_dash="dash", line_color="#f6465d", opacity=0.5)
        fig.add_hline(y=30, row=2, col=1, line_dash="dash", line_color="#0ecb81", opacity=0.5)

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#181a20",
            plot_bgcolor="#181a20",
            height=580,
            margin=dict(l=10, r=10, t=40, b=10),
            legend=dict(orientation="h", y=1.02, x=0.1)
        )
        st.plotly_chart(fig, use_container_width=True)

# ----- TAB 3: مقارنة الأزواج (Comparison Table) -----
with tab_compare:
    st.subheader("مقارنة مؤشرات السوق عبر الأزواج")
    comp_tf = st.selectbox("الإطار الزمني للمقارنة:", TIMEFRAMES, key="cp_tf")
    
    rows = run_query(
        "SELECT DISTINCT ON (symbol) symbol, last_price, rsi_14, ema_20, ema_50, atr_14, created_at FROM technical_snapshots WHERE timeframe = %s ORDER BY symbol, created_at DESC",
        (comp_tf,)
    )
    if rows:
        df_cp = pd.DataFrame(rows)
        
        # تلوين مشروط لجدول البيانات
        def style_rsi(val):
            if val >= 70:
                return 'background-color: #f6465d22; color: #f6465d; font-weight:bold;'
            elif val <= 30:
                return 'background-color: #0ecb8122; color: #0ecb81; font-weight:bold;'
            return 'color: #eaecef;'

        styled_df = df_cp.style.applymap(style_rsi, subset=['rsi_14']).format({
            'last_price': '{:.5f}',
            'rsi_14': '{:.2f}',
            'ema_20': '{:.5f}',
            'ema_50': '{:.5f}',
            'atr_14': '{:.5f}'
        })
        
        st.dataframe(styled_df, use_container_width=True, height=400)

# ----- TAB 4: تقارير الذكاء الاصطناعي المخزنة -----
with tab_ai:
    st.subheader("استعراض تقارير التحليل المتقدمة")
    c_q1, c_q2 = st.columns(2)
    q_type = c_q1.selectbox("نوع التقرير:", ["full", "quick_signals", "forex_factory", "finnhub"])
    q_sym = c_q2.text_input("رمز الزوج:", value="XAUUSD")
    
    if st.button("🔍 جلب التقرير"):
        reports = run_query(
            "SELECT report_text, created_at FROM ai_reports WHERE analysis_type = %s AND symbols LIKE %s ORDER BY created_at DESC LIMIT 1",
            (q_type, f"%{q_sym}%")
        )
        if reports:
            st.success(f"تاريخ التقرير: {reports[0]['created_at']}")
            st.markdown(f'<div style="background:#181a20; padding:20px; border-radius:12px; border:1px solid #2b313a;">{reports[0]["report_text"]}</div>', unsafe_allow_html=True)
        else:
            st.warning("لم يتم العثور على تقرير مطابق للبيانات المحددة.")