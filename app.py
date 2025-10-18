import streamlit as st
import pandas as pd

# ------------------ App Config ------------------
st.set_page_config(page_title="ONDC TAT Breach Dashboard", layout="wide")
st.markdown("<br>", unsafe_allow_html=True)
st.title("ONDC TAT Breach Dashboard")

# ------------------ Base Light Theme ------------
st.markdown("""
<style>
html, body, [class^="css"]  { background-color: #ffffff !important; color:#111827 !important; }
.block-container { padding-top: 1.5rem; }
.stDataFrame [data-testid="stTable"] th { background:#f3f4f6 !important; color:#111827 !important; }
.stDataFrame [data-testid="stTable"] td { background:#ffffff !important; color:#111827 !important; }
.stDownloadButton > button, .stButton > button {
  background:#ffffff !important; color:#111827 !important; border:1px solid #d1d5db !important;
}
pre.note { white-space: pre-wrap; word-break: break-word; background:#f9fafb; border:1px solid #e5e7eb; padding:.75rem; border-radius:.5rem; }
</style>
""", unsafe_allow_html=True)

# ------------------ Helpers ---------------------
BREACH_NOTE_GRACE_MIN = 5  # minutes window for "within 5 mins of breach"

def normalize(s: str) -> str:
    return str(s or "").lower().strip().replace("\n", " ").replace("\t", " ").replace("  ", " ")

def to_dt(x):
    if x is None or x == "" or (isinstance(x, float) and pd.isna(x)):
        return pd.NaT
    try:
        return pd.to_datetime(x, errors="coerce")
    except Exception:
        return pd.NaT

def diff_min(a, b):
    if pd.isna(a) or pd.isna(b): return None
    try: return max(0, (b - a).total_seconds()/60.0)
    except Exception: return None

def fmt_time(x):
    if pd.isna(x): return "—"
    try: return pd.to_datetime(x).strftime("%Y-%m-%d %H:%M")
    except: return "—"

# ------------------ Stage config ----------------
STAGE_LABELS = {
    "created_to_placed": "Created → Placed",
    "placed_to_accepted": "Placed → Accepted",
    "accepted_to_in_kitchen": "Order Accepted → Kitchen",
    "in_kitchen_to_ready": "In Kitchen → Ready",
    "ready_to_shipped": "Ready → Shipped",
}
THRESHOLDS = {
    "created_to_placed": 5,    # treat "tpl_pending" as "order_placed" by using this stage
    "placed_to_accepted": 7,
    "accepted_to_in_kitchen": 5,
    "in_kitchen_to_ready": 15,
    "ready_to_shipped": 10,
}
STAGE_ORDER = [
    "created_to_placed",
    "placed_to_accepted",
    "accepted_to_in_kitchen",
    "in_kitchen_to_ready",
    "ready_to_shipped",
]

def compute_breaches(order_row: pd.Series):
    stages = []

    def add_stage(key, start, end):
        dur = diff_min(start, end)
        stages.append({
            "key": key,
            "label": STAGE_LABELS[key],
            "threshold": THRESHOLDS[key],
            "duration": dur,
            "breached": (dur is not None and dur > THRESHOLDS[key]),
            "segmentStart": start,
            "segmentEnd": end
        })

    add_stage("created_to_placed", order_row["createdOn"],   order_row["placedAt"])
    add_stage("placed_to_accepted", order_row["placedAt"],   order_row["acceptedAt"])
    add_stage("accepted_to_in_kitchen", order_row["acceptedAt"], order_row["readyAt"])
    add_stage("in_kitchen_to_ready",    order_row["acceptedAt"], order_row["readyAt"])
    add_stage("ready_to_shipped",   order_row["readyAt"],    order_row["shippedAt"])

    breached = [s for s in stages if s["breached"] and not pd.isna(s["segmentEnd"])]
    first_breach = None
    earliest_breach_time = pd.NaT
    if breached:
        breached = sorted(breached, key=lambda s: s["segmentEnd"])
        first_breach = breached[0]
        earliest_breach_time = first_breach["segmentEnd"]

    return stages, first_breach, earliest_breach_time

# ------------------ Headers ----------------
ORDER_ID_ALIASES = [
    "Network Order Id", "Network Order ID", "Network order id", "order id",
    "Order ID", "Order No", "Order Number", "Order #", "Order Reference", "Network Ref"
]
ORDERS_COL_ALIASES = {
    "createdOn": ["Created On", "Created", "Created Date", "Created Time"],
    "placedAt":  ["Order Placed Time", "Placed At", "Order Placed", "Placed Time"],
    "acceptedAt":["Order Accepted Time", "Accepted At", "Order Accepted", "Accepted Time"],
    "readyAt":   ["Order Ready Time", "Ready At", "Order Ready", "Ready Time"],
    "shippedAt": ["Shipped At Date & Time", "Shipped at", "Shipped At", "Shipped Time", "Out For Delivery"],
}
NOTES_ID_ALIASES = [
    "Network order ID", "Network Order Id", "Network Order ID", "Network order id",
    "Order ID", "Order No", "Order Number", "Order #", "Order Reference", "Network Ref"
]
NOTES_COL_ALIASES = {
    "noteAt": ["Created at", "Note Time", "Created On", "Created"],
    "description": ["Description", "Notes", "Comment", "Body"],
    "agent": ["Reported by", "Agent", "Agent Name", "User", "Updated By", "Created By", "Author", "Owner", "Assignee"]
}

def pick(row: pd.Series, candidates):
    keys = {normalize(k): k for k in row.index}
    for c in candidates:
        k = keys.get(normalize(c))
        if k is not None:
            return row[k]
    return None

def has_any(colset, aliases):
    norm = {normalize(c) for c in colset}
    return any(normalize(a) in norm for a in aliases)

def validate_orders_columns(df: pd.DataFrame):
    miss = []
    if not has_any(df.columns, ORDER_ID_ALIASES):
        miss.append("any of " + ", ".join(ORDER_ID_ALIASES))
    for field, aliases in ORDERS_COL_ALIASES.items():
        if not has_any(df.columns, aliases):
            miss.append(f"any of {aliases} for '{field}'")
    return miss

def validate_notes_columns(df: pd.DataFrame):
    miss = []
    if not has_any(df.columns, NOTES_ID_ALIASES):
        miss.append("any of " + ", ".join(NOTES_ID_ALIASES))
    if not has_any(df.columns, NOTES_COL_ALIASES["noteAt"]):
        miss.append("any of " + ", ".join(NOTES_COL_ALIASES["noteAt"]))
    return miss

def map_orders(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for _, r in df.iterrows():
        idv = pick(r, ORDER_ID_ALIASES)
        if pd.isna(idv): continue
        out.append({
            "id": str(idv).strip(),
            "createdOn": to_dt(pick(r, ORDERS_COL_ALIASES["createdOn"])),
            "placedAt":  to_dt(pick(r, ORDERS_COL_ALIASES["placedAt"])),
            "acceptedAt":to_dt(pick(r, ORDERS_COL_ALIASES["acceptedAt"])),
            "readyAt":   to_dt(pick(r, ORDERS_COL_ALIASES["readyAt"])),
            "shippedAt": to_dt(pick(r, ORDERS_COL_ALIASES["shippedAt"])),
        })
    return pd.DataFrame(out)

def map_notes(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for _, r in df.iterrows():
        idv = pick(r, NOTES_ID_ALIASES)
        if pd.isna(idv): continue
        out.append({
            "id": str(idv).strip(),
            "noteAt": to_dt(pick(r, NOTES_COL_ALIASES["noteAt"])),
            "description": pick(r, NOTES_COL_ALIASES["description"]) or "",
            "agent": (pick(r, NOTES_COL_ALIASES.get("agent", [])) or "").strip()
        })
    return pd.DataFrame(out)

def load_with_header_auto(file, preferred_header_index=None, is_orders=False):
    def _read(idx):
        try:
            return pd.read_excel(file, sheet_name=0, header=idx)
        except Exception:
            return None
    if preferred_header_index is not None:
        df = _read(preferred_header_index)
        if df is not None:
            miss = validate_orders_columns(df) if is_orders else validate_notes_columns(df)
            if not miss:
                return df
    for idx in range(0, 31):
        df = _read(idx)
        if df is None:
            continue
        miss = validate_orders_columns(df) if is_orders else validate_notes_columns(df)
        if not miss:
            return df
    return _read(preferred_header_index or 0)

# ------------------ Upload ----------------------
with st.sidebar:
    st.markdown("### Upload Excel files")
    orders_file = st.file_uploader("Orders workbook (headers start on row 12)", type=["xlsx","xls"])
    notes_file  = st.file_uploader("Notes workbook", type=["xlsx","xls"])

if not orders_file or not notes_file:
    st.info("Upload both **Orders** and **Notes** Excel files to begin.")
    st.stop()

orders_raw = load_with_header_auto(orders_file, preferred_header_index=11, is_orders=True)
notes_raw  = load_with_header_auto(notes_file, preferred_header_index=0,  is_orders=False)

miss_orders = validate_orders_columns(orders_raw)
miss_notes  = validate_notes_columns(notes_raw)
if miss_orders or miss_notes:
    if miss_orders:
        st.error("Missing columns in Orders:\n- " + "\n- ".join(miss_orders))
    if miss_notes:
        st.error("Missing columns in Notes:\n- " + "\n- ".join(miss_notes))
    st.stop()

orders = map_orders(orders_raw)
notes  = map_notes(notes_raw)

notes = notes.sort_values("noteAt", na_position="first")
notes_by_id = notes.groupby("id")

enriched = []
earliest_breach_by_id = {}
for _, row in orders.iterrows():
    stages, first_breach, earliest_breach_time = compute_breaches(row)
    group = notes_by_id.get_group(row["id"]) if row["id"] in notes_by_id.groups else pd.DataFrame(columns=notes.columns)
    enriched.append({
        "id": row["id"],
        "stages": stages,
        "first_breach": first_breach,
        "earliest_breach_time": earliest_breach_time,
        "createdOn": row["createdOn"], "placedAt": row["placedAt"],
        "acceptedAt": row["acceptedAt"], "readyAt": row["readyAt"], "shippedAt": row["shippedAt"],
        "notes": group
    })
    earliest_breach_by_id[row["id"]] = earliest_breach_time

# ------------------ KPIs -------------------------
counts_by_stage = {k:0 for k in STAGE_ORDER}
orders_with_breach = 0
for er in enriched:
    any_breach = False
    for s in er["stages"]:
        if s["breached"]:
            counts_by_stage[s["key"]] += 1
            any_breach = True
    if any_breach:
        orders_with_breach += 1
total_breaches = sum(counts_by_stage.values())

total_notes_created = len(notes)
orders_with_notes = notes["id"].nunique()

st.subheader("Metrics")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total Orders", f"{len(orders)}")
c2.metric("Orders With Any Breach", f"{orders_with_breach}")
c3.metric("Orders Without Breach", f"{len(orders)-orders_with_breach}")
c4.metric("Total Breaches (All Stages)", f"{total_breaches}")
c5.metric("Total Notes Created", f"{total_notes_created}")
c6.metric("Orders With Notes", f"{orders_with_notes}")

# ------------------ TAT Breach summary table  ---------------------
st.subheader("TAT Breach Summary Table")
summary_df = pd.DataFrame([{
    "Stage": STAGE_LABELS[k],
    "Breach in time system configured": THRESHOLDS[k],
    "Breached Count": counts_by_stage[k]
} for k in STAGE_ORDER])
st.dataframe(summary_df, use_container_width=True)

# ------------------ Agent Level Metrics - Notes --------
st.subheader("Agent Level Metrics - Notes")

def _nz_agent(x):
    x = str(x or "").strip()
    return x if x else "Unknown"

agent_grp = notes.assign(agent=notes["agent"].apply(_nz_agent)).groupby("agent", dropna=False)
agent_df = pd.DataFrame({
    "agent name": agent_grp.size().index,
    "number of notes added": agent_grp.size().values,
    "unique order count": agent_grp["id"].nunique().values
}).sort_values(["number of notes added", "unique order count"], ascending=[False, False])

st.dataframe(agent_df, use_container_width=True)

import io

import io

# ------------------ Order-Level table: multi-breach stages + breach flag ------------------
st.subheader("Order Level TAT Breach & Notes Table")

def fmt_td_gap(breach_time, note_time):
    if pd.isna(breach_time) or pd.isna(note_time):
        return "—"
    try:
        delta = note_time - breach_time
        secs = int(delta.total_seconds())
        sign = "-" if secs < 0 else ""
        secs = abs(secs)
        m, s = divmod(secs, 60)
        return f"{sign}{m:02d}:{s:02d}"
    except Exception:
        return "—"

out_rows = []
for er in enriched:
    stages = er["stages"]
    breached_stages = [s for s in stages if not pd.isna(s.get("segmentEnd"))]

    if not breached_stages:
        out_rows.append({
            "Network Order ID": er["id"],
            "TAT Breached (Yes/No)": "—",
            "TAT Breached at Stage": "—",
            "TAT Breached at Time": "—",
            "Notes Added Time": "—",
            "Agent": "—",
            "Note Description": "—",
            "Notes added within 5 mins of order stage TAT breached": "—",
            "Notes added after 5 mins of order stage TAT breached": "—",
            "Time gap between TAT breached and Notes added (mm:ss)": "—",
        })
        continue

    for stage in breached_stages:
        tat_stage_label = STAGE_LABELS.get(stage["key"], stage["key"])
        tat_time = stage.get("segmentEnd")
        breached_flag = stage.get("breached", False)

        tat_breached_display = "🟢 Yes" if breached_flag else "🔴 No"

        # If no notes, still show one line per stage
        if er["notes"].empty:
            out_rows.append({
                "Network Order ID": er["id"],
                "TAT Breached (Yes/No)": tat_breached_display,
                "TAT Breached at Stage": tat_stage_label,
                "TAT Breached at Time": fmt_time(tat_time),
                "Notes Added Time": "—",
                "Agent": "—",
                "Note Description": "—",
                "Notes added within 5 mins of order stage TAT breached": "—",
                "Notes added after 5 mins of order stage TAT breached": "—",
                "Time gap between TAT breached and Notes added (mm:ss)": "—",
            })
        else:
            for _, n in er["notes"].iterrows():
                note_time = n.get("noteAt")
                note_agent = n.get("agent", "—")
                note_desc = n.get("description", "—")

                within5 = "—"
                after5 = "—"
                if breached_flag and not pd.isna(tat_time) and not pd.isna(note_time):
                    if tat_time <= note_time <= tat_time + pd.Timedelta(minutes=BREACH_NOTE_GRACE_MIN):
                        within5 = "🟢 Yes"
                    elif note_time > tat_time + pd.Timedelta(minutes=BREACH_NOTE_GRACE_MIN):
                        after5 = "🔴 Yes"

                out_rows.append({
                    "Network Order ID": er["id"],
                    "TAT Breached (Yes/No)": tat_breached_display,
                    "TAT Breached at Stage": tat_stage_label,
                    "TAT Breached at Time": fmt_time(tat_time),
                    "Notes Added Time": fmt_time(note_time),
                    "Agent": str(note_agent) if note_agent else "—",
                    "Note Description": str(note_desc) if note_desc else "—",
                    "Notes added within 5 mins of order stage TAT breached": within5,
                    "Notes added after 5 mins of order stage TAT breached": after5,
                    "Time gap between TAT breached and Notes added (mm:ss)": fmt_td_gap(tat_time, note_time),
                })

out_df = pd.DataFrame(out_rows)
st.dataframe(out_df, use_container_width=True, height=650)

# ------------------ Excel Export ------------------
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
    out_df.to_excel(writer, index=False, sheet_name="Order_Level_TAT_Breach")
    writer.close()
buffer.seek(0)

st.download_button(
    label="Download Order-Level Output (Excel)",
    data=buffer,
    file_name="order_level_output.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
