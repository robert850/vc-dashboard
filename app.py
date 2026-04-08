import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import io
import re
from datetime import datetime, timedelta

# --- Config ---
st.set_page_config(page_title="VC Outreach Dashboard", layout="wide")

SHEET_CONFIGS = {
    "Rigitech": {
        "id": "1njgDTpSpOWhLGTtfg2BzGAlFKezoUBGKF-qkXOvwxgA",
        "columns": {
            "Fund": "Fund",
            "Status": "Status",
            "Website": "Website",
            "Zoe notes": "Notes",
            "Sector": "Sector",
            "Investment Geography": "Geography",
            "Ticket Size": "Ticket Size",
        },
    },
    "Curators": {
        "id": "1YBIMB0BPw0F4wfkiKEzt_vylG6N60grFqFY9KZO_gUE",
        "columns": {
            "Fund": "Fund",
            "Status": "Status",
            "Website": "Website",
            "Zoe's Notes": "Notes",
            "Sector": "Sector",
            "Area": "Geography",
            "Tickets": "Ticket Size",
        },
    },
}

STATUS_ORDER = ["To Start Process", "Awaiting Email", "In Drafts", "Email Sent"]
STATUS_COLORS = {
    "To Start Process": "#EF4444",
    "Awaiting Email": "#F59E0B",
    "In Drafts": "#3B82F6",
    "Email Sent": "#10B981",
}
STALE_DAYS = 10


@st.cache_data(ttl=3600)
def load_sheet(sheet_id: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


def normalize(df: pd.DataFrame, col_map: dict, deal_name: str) -> pd.DataFrame:
    rename = {}
    for orig, standard in col_map.items():
        matches = [c for c in df.columns if c.strip().lower() == orig.lower()]
        if matches:
            rename[matches[0]] = standard
    df = df.rename(columns=rename)
    keep = [c for c in ["Fund", "Status", "Website", "Notes", "Sector", "Geography", "Ticket Size"] if c in df.columns]
    df = df[keep].copy()
    df["Deal"] = deal_name
    return df


def extract_latest_date(notes: str) -> datetime | None:
    if not isinstance(notes, str):
        return None
    dates = re.findall(r"(\d{1,2}/\d{1,2}/\d{4})", notes)
    parsed = []
    for d in dates:
        try:
            parsed.append(datetime.strptime(d, "%d/%m/%Y"))
        except ValueError:
            pass
    return max(parsed) if parsed else None


def load_all_data() -> pd.DataFrame:
    frames = []
    for deal_name, cfg in SHEET_CONFIGS.items():
        try:
            raw = load_sheet(cfg["id"])
            df = normalize(raw, cfg["columns"], deal_name)
            frames.append(df)
        except Exception as e:
            st.warning(f"Failed to load {deal_name}: {e}")
    if not frames:
        st.error("No data loaded.")
        st.stop()
    combined = pd.concat(frames, ignore_index=True)
    combined["Status"] = combined["Status"].fillna("").str.strip()
    combined.loc[~combined["Status"].isin(STATUS_ORDER), "Status"] = "To Start Process"
    combined["Latest Activity"] = combined["Notes"].apply(extract_latest_date)
    combined["Days Since Activity"] = combined["Latest Activity"].apply(
        lambda d: (datetime.now() - d).days if d else None
    )
    return combined


# --- Load data ---
data = load_all_data()

# --- Header ---
st.title("VC Outreach Dashboard")
st.caption(f"Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(data)} total targets")

# --- Deal filter ---
deals = ["All Deals"] + sorted(data["Deal"].unique().tolist())
selected_deal = st.selectbox("Filter by Deal", deals)
if selected_deal != "All Deals":
    filtered = data[data["Deal"] == selected_deal].copy()
else:
    filtered = data.copy()

# --- KPI Cards ---
col1, col2, col3, col4, col5 = st.columns(5)
total = len(filtered)
status_counts = filtered["Status"].value_counts()

col1.metric("Total Targets", total)
col2.metric("To Start", status_counts.get("To Start Process", 0))
col3.metric("Awaiting Email", status_counts.get("Awaiting Email", 0))
col4.metric("In Drafts", status_counts.get("In Drafts", 0))
col5.metric("Email Sent", status_counts.get("Email Sent", 0))

st.divider()

# --- Stale Leads ---
st.subheader("Stale Leads (no activity in 10+ days)")
stale = filtered[filtered["Days Since Activity"] >= STALE_DAYS].sort_values(
    "Days Since Activity", ascending=False
)
no_date = filtered[filtered["Latest Activity"].isna()]

if len(stale) > 0:
    stale_display = stale[["Fund", "Deal", "Status", "Days Since Activity", "Latest Activity"]].copy()
    stale_display["Latest Activity"] = stale_display["Latest Activity"].dt.strftime("%Y-%m-%d")
    st.dataframe(stale_display, use_container_width=True, hide_index=True)
else:
    st.success("No stale leads!")

if len(no_date) > 0:
    with st.expander(f"Leads with no date in notes ({len(no_date)})"):
        st.dataframe(
            no_date[["Fund", "Deal", "Status"]],
            use_container_width=True,
            hide_index=True,
        )

st.divider()

# --- Charts row ---
chart_left, chart_right = st.columns(2)

# Funnel chart
with chart_left:
    st.subheader("Outreach Funnel")
    funnel_data = []
    for status in STATUS_ORDER:
        count = status_counts.get(status, 0)
        funnel_data.append({"Status": status, "Count": count})
    funnel_df = pd.DataFrame(funnel_data)

    fig_funnel = go.Figure(
        go.Funnel(
            y=funnel_df["Status"],
            x=funnel_df["Count"],
            marker=dict(color=[STATUS_COLORS[s] for s in STATUS_ORDER]),
            textinfo="value+percent initial",
        )
    )
    fig_funnel.update_layout(margin=dict(l=20, r=20, t=20, b=20), height=350)
    st.plotly_chart(fig_funnel, use_container_width=True)

# Deal-by-deal breakdown
with chart_right:
    st.subheader("Deal-by-Deal Breakdown")
    deal_status = (
        filtered.groupby(["Deal", "Status"]).size().reset_index(name="Count")
    )
    deal_status["Status"] = pd.Categorical(
        deal_status["Status"], categories=STATUS_ORDER, ordered=True
    )
    deal_status = deal_status.sort_values("Status")

    fig_deal = px.bar(
        deal_status,
        x="Deal",
        y="Count",
        color="Status",
        color_discrete_map=STATUS_COLORS,
        barmode="stack",
    )
    fig_deal.update_layout(margin=dict(l=20, r=20, t=20, b=20), height=350)
    st.plotly_chart(fig_deal, use_container_width=True)

st.divider()

# --- Status distribution pie ---
st.subheader("Status Distribution")
fig_pie = px.pie(
    filtered,
    names="Status",
    color="Status",
    color_discrete_map=STATUS_COLORS,
    hole=0.4,
)
fig_pie.update_layout(margin=dict(l=20, r=20, t=20, b=20), height=350)
st.plotly_chart(fig_pie, use_container_width=True)

st.divider()

# --- Full data table ---
st.subheader("All Leads")
display_cols = ["Fund", "Deal", "Status", "Sector", "Geography", "Ticket Size", "Days Since Activity"]
display_cols = [c for c in display_cols if c in filtered.columns]
st.dataframe(
    filtered[display_cols].sort_values(["Deal", "Status"]),
    use_container_width=True,
    hide_index=True,
)
