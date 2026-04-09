import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import io
import re
from datetime import datetime
from typing import Optional

st.set_page_config(page_title="VC Outreach Dashboard", layout="wide")

SHEETS = {
    "Rigitech": {
        "id": "1njgDTpSpOWhLGTtfg2BzGAlFKezoUBGKF-qkXOvwxgA",
        "col_map": {
            "fund": "Fund",
            "status": "Status",
            "website": "Website",
            "zoe notes": "Zoe Notes",
            "sector": "Sector",
            "investment geography": "Geography",
            "ticket size": "Ticket Size",
            "date of last action": "Date of Last Action",
        },
        "drop": ["Notes"],
    },
    "Curators": {
        "id": "1YBIMB0BPw0F4wfkiKEzt_vylG6N60grFqFY9KZO_gUE",
        "col_map": {
            "fund": "Fund",
            "status": "Status",
            "website": "Website",
            "zoe's notes": "Zoe Notes",
            "sector": "Sector",
            "area": "Geography",
            "tickets": "Ticket Size",
            "date of last action": "Date of Last Action",
        },
        "drop": [],
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
STANDARD_COLS = ["Fund", "Status", "Website", "Zoe Notes", "Sector", "Geography", "Ticket Size", "Date of Last Action"]


@st.cache_data(ttl=3600)
def load_sheet(sheet_id: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


def normalize(df: pd.DataFrame, col_map: dict, deal_name: str, drop_cols: list = None) -> pd.DataFrame:
    # Strip whitespace from column names
    df.columns = [c.strip() for c in df.columns]
    # Drop ambiguous columns before renaming
    if drop_cols:
        df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")
    # Case-insensitive rename
    lower_map = {k.lower(): v for k, v in col_map.items()}
    rename = {}
    for col in df.columns:
        mapped = lower_map.get(col.strip().lower())
        if mapped:
            rename[col] = mapped
    df = df.rename(columns=rename)
    keep = [c for c in STANDARD_COLS if c in df.columns]
    df = df[keep].copy()
    df["Deal"] = deal_name
    return df


def extract_latest_date(notes: str) -> Optional[datetime]:
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
    for deal_name, cfg in SHEETS.items():
        try:
            raw = load_sheet(cfg["id"])
            df = normalize(raw, cfg["col_map"], deal_name, cfg.get("drop", []))
            frames.append(df)
        except Exception as e:
            st.warning(f"Failed to load {deal_name}: {e}")
    if not frames:
        st.error("No data loaded.")
        st.stop()
    combined = pd.concat(frames, ignore_index=True)
    combined["Status"] = combined["Status"].fillna("").str.strip()
    combined.loc[~combined["Status"].isin(STATUS_ORDER), "Status"] = "To Start Process"
    combined["Latest Activity"] = combined["Zoe Notes"].apply(extract_latest_date)
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
filtered = data if selected_deal == "All Deals" else data[data["Deal"] == selected_deal].copy()

# --- KPI Cards ---
col1, col2, col3, col4, col5 = st.columns(5)
counts = filtered["Status"].value_counts()
col1.metric("Total Targets", len(filtered))
col2.metric("To Start", counts.get("To Start Process", 0))
col3.metric("Awaiting Email", counts.get("Awaiting Email", 0))
col4.metric("In Drafts", counts.get("In Drafts", 0))
col5.metric("Email Sent", counts.get("Email Sent", 0))

st.divider()

# --- Stale Leads ---
st.subheader("Stale Leads (no activity in 10+ days)")
stale = filtered[filtered["Days Since Activity"] >= STALE_DAYS].sort_values("Days Since Activity", ascending=False)
no_date = filtered[filtered["Latest Activity"].isna()]

if len(stale) > 0:
    stale_display = stale[["Fund", "Deal", "Status", "Days Since Activity", "Latest Activity"]].copy()
    stale_display["Latest Activity"] = stale_display["Latest Activity"].dt.strftime("%Y-%m-%d")
    st.dataframe(stale_display, use_container_width=True, hide_index=True)
else:
    st.success("No stale leads!")

if len(no_date) > 0:
    with st.expander(f"Leads with no date in notes ({len(no_date)})"):
        st.dataframe(no_date[["Fund", "Deal", "Status"]], use_container_width=True, hide_index=True)

st.divider()

# --- Charts ---
left, right = st.columns(2)

with left:
    st.subheader("Outreach Funnel")
    funnel_df = pd.DataFrame([{"Status": s, "Count": counts.get(s, 0)} for s in STATUS_ORDER])
    fig = go.Figure(go.Funnel(
        y=funnel_df["Status"],
        x=funnel_df["Count"],
        marker=dict(color=[STATUS_COLORS[s] for s in STATUS_ORDER]),
        textinfo="value+percent initial",
    ))
    fig.update_layout(margin=dict(l=20, r=20, t=20, b=20), height=350)
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Deal-by-Deal Breakdown")
    deal_status = filtered.groupby(["Deal", "Status"]).size().reset_index(name="Count")
    deal_status["Status"] = pd.Categorical(deal_status["Status"], categories=STATUS_ORDER, ordered=True)
    fig2 = px.bar(deal_status.sort_values("Status"), x="Deal", y="Count", color="Status",
                  color_discrete_map=STATUS_COLORS, barmode="stack")
    fig2.update_layout(margin=dict(l=20, r=20, t=20, b=20), height=350)
    st.plotly_chart(fig2, use_container_width=True)

st.divider()

# --- Status pie ---
st.subheader("Status Distribution")
fig3 = px.pie(filtered, names="Status", color="Status", color_discrete_map=STATUS_COLORS, hole=0.4)
fig3.update_layout(margin=dict(l=20, r=20, t=20, b=20), height=350)
st.plotly_chart(fig3, use_container_width=True)

st.divider()

# --- Full table ---
st.subheader("All Leads")
display_cols = [c for c in ["Fund", "Deal", "Status", "Sector", "Geography", "Ticket Size", "Days Since Activity"] if c in filtered.columns]
st.dataframe(filtered[display_cols].sort_values(["Deal", "Status"]), use_container_width=True, hide_index=True)
