import streamlit as st
import pandas as pd

# ------------------ App Config ------------------
st.set_page_config(page_title="ONDC TAT Breach Dashboard", layout="wide")
st.title("ONDC TAT Breach Dashboard")

# ------------------ Base Light Theme ------------
st.markdown("""
<style>
html, body, [class^="css"]  {
    background-color: #ffffff !important;
    color: #111827 !important;
}
.block-container { padding-top: 1.5rem; }
.stDataFrame [data-testid="stTable"] th {
    background:#f3f4f6 !important; color:#111827 !important;
}
.stDataFrame [data-testid="stTable"] td {
    background:#ffffff !important; color:#111827 !important;
}
.stDownloadButton > button, .stButton > button {
    background:#ffffff !important; color:#111827 !important; border:1px solid #d1d5db !important;
}
</style>
""", unsafe_allow_html=True)

# ------------------ Helpers ---------------------
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
    try: return pd.to_datetime(x).strftime("%H:%M")
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
    "created_to_placed": 5,
    "placed_to_accepted": 7,
    "accepted_to_in_kitchen": 5,
    "in_kitchen_to_ready": 15,
    "ready_to_shipped": 10,
}
STAGE_ORDER = list(STAGE_LABELS.keys())

def compute_breaches(order_row: pd.Series):
    stages = []
    a = diff_min(order_row["createdOn"], order_row["placedAt"])
    stages.append({"key":"created_to_placed","label":STAGE_LABELS["created_to_placed"],"threshold":THRESHOLDS["created_to_placed"],"duration":a,"breached":(a is not None and a>THRESHOLDS["created_to_placed"]),"segmentEnd":order_row["placedAt"]})
    b = diff_min(order_row["placedAt"], order_row["acceptedAt"])
    stages.append({"key":"placed_to_accepted","label":STAGE_LABELS["placed_to_accepted"],"threshold":THRESHOLDS["placed_to_accepted"],"duration":b,"breached":(b is not None and b>THRESHOLDS["placed_to_accepted"]),"segmentEnd":order_row["acceptedAt"]})
    c = diff_min(order_row["acceptedAt"], order_row["readyAt"])
    stages.append({"key":"accepted_to_in_kitchen","label":STAGE_LABELS["accepted_to_in_kitchen"],"threshold":THRESHOLDS["accepted_to_in_kitchen"],"duration":c,"breached":(c is not None and c>THRESHOLDS["accepted_to_in_kitchen"]),"segmentEnd":order_row["readyAt"]})
    stages.append({"key":"in_kitchen_to_ready","label":STAGE_LABELS["in_kitchen_to_ready"],"threshold":THRESHOLDS["in_kitchen_to_ready"],"duration":c,"breached":(c is not None and c>THRESHOLDS["in_kitchen_to_ready"]),"segmentEnd":order_row["readyAt"]})
    d = diff_min(order_row["readyAt"], order_row["shippedAt"])
    stages.append({"key":"ready_to_shipped","label":STAGE_LABELS["ready_to_shipped"],"threshold":THRESHOLDS["ready_to_shipped"],"duration":d,"breached":(d is not None and d>THRESHOLDS["ready_to_shipped"]),"segmentEnd":order_row["shippedAt"]})
    breached = [s for s in stages if s["breached"]]
    first_breach = None
    if breached:
        breached = sorted(breached, key=lambda s: (pd.Timestamp.min if pd.isna(s["segmentEnd"]) else s["segmentEnd"]))
        first_breach = breached[0]
    return stages, first_breach

# ------------------ Header aliasing --------------
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
        miss.append("Orders: any of " + ", ".join(ORDER_ID_ALIASES))
    for field, aliases in ORDERS_COL_ALIASES.items():
        if not has_any(df.columns, aliases):
            miss.append(f"Orders: any of {aliases} for '{field}'")
    return miss

def validate_notes_columns(df: pd.DataFrame):
    miss = []
    if not has_any(df.columns, NOTES_ID_ALIASES):
        miss.append("Notes: any of " + ", ".join(NOTES_ID_ALIASES))
    if not has_any(df.columns, NOTES_COL_ALIASES["noteAt"]):
        miss.append("Notes: any of " + ", ".join(NOTES_COL_ALIASES["noteAt"]))
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

# ------------------ Enrich -----------------------
notes = notes.sort_values("noteAt", na_position="first")
notes_by_id = notes.groupby("id")

enriched = []
for _, row in orders.iterrows():
    stages, first_breach = compute_breaches(row)
    group = notes_by_id.get_group(row["id"]) if row["id"] in notes_by_id.groups else pd.DataFrame(columns=notes.columns)
    nb = []
    for _, n in group.iterrows():
        after = any(s["breached"] and (not pd.isna(s["segmentEnd"])) and (not pd.isna(n["noteAt"])) and n["noteAt"] > s["segmentEnd"] for s in stages)
        nb.append({**n.to_dict(), "afterAnyBreach": after})
    enriched.append({
        "id": row["id"],
        "stages": stages,
        "first_breach": first_breach,
        "createdOn": row["createdOn"], "placedAt": row["placedAt"],
        "acceptedAt": row["acceptedAt"], "readyAt": row["readyAt"], "shippedAt": row["shippedAt"],
        "notes": nb
    })

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

# ------------------ Summary ---------------------
st.subheader("Breach Summary by Stage")
summary_df = pd.DataFrame([{
    "Stage": STAGE_LABELS[k],
    "Threshold (min)": THRESHOLDS[k],
    "Breached Count": counts_by_stage[k]
} for k in STAGE_ORDER])
st.dataframe(summary_df, use_container_width=True)
st.download_button("Download Summary CSV", summary_df.to_csv(index=False).encode("utf-8"),
                   file_name="breach_summary_by_stage.csv", mime="text/csv")

# ------------------ Output Table ----------------
st.subheader("Order-Level Details (📊 Output Example)")
out_rows = []
for er in enriched:
    fb = er["first_breach"]
    first_stage = STAGE_LABELS.get(fb["key"], "None") if fb else "None"
    breach_time = fb["segmentEnd"] if fb else pd.NaT
    latest_note = er["notes"][-1] if len(er["notes"]) else None
    note_time = latest_note["noteAt"] if latest_note is not None else pd.NaT
    note_desc = latest_note["description"] if latest_note is not None else ""
    if latest_note is None:
        note_status = "—"
    else:
        note_status = "🔴 After breach" if (not pd.isna(breach_time) and not pd.isna(note_time) and note_time > breach_time) else "🟢 Before breach"
    out_rows.append({
        "Network Order ID": er["id"],
        "Breached Stage": first_stage,
        "Breach Time": fmt_time(breach_time),
        "Notes Added Time": fmt_time(note_time),
        "Note Description": str(note_desc) if note_desc is not None else "",
        "Note Added Status": note_status
    })
out_df = pd.DataFrame(out_rows)
st.dataframe(out_df, use_container_width=True)
st.download_button("Download Output CSV", out_df.to_csv(index=False).encode("utf-8"),
                   file_name="order_level_output.csv", mime="text/csv")

st.caption("Note: Orders loader assumes headers at row 12 by default and auto-detects if structure varies.")
