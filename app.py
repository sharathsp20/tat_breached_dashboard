import streamlit as st
import pandas as pd

st.set_page_config(page_title="ONDC TAT Breach Dashboard", layout="wide")
st.title("ONDC TAT Breach Dashboard (with Column Mapper)")

# ---------- Helpers ----------
def normalize(s: str) -> str:
    return str(s or "").strip()

def to_dt(x):
    """Robust: handles Excel serials, strings, timestamps, NaT."""
    if x is None or x == "" or (isinstance(x, float) and pd.isna(x)):
        return pd.NaT
    try:
        # Try pandas first
        dt = pd.to_datetime(x, errors="coerce")
        if pd.isna(dt):
            return pd.NaT
        return dt
    except Exception:
        return pd.NaT

def diff_min(a, b):
    if pd.isna(a) or pd.isna(b):
        return None
    try:
        return max(0, (b - a).total_seconds() / 60.0)
    except Exception:
        return None

def fmt_time(x):
    if pd.isna(x):
        return "—"
    try:
        return pd.to_datetime(x).strftime("%H:%M")
    except Exception:
        return "—"

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
    "accepted_to_in_kitchen": 5,   # part of 20
    "in_kitchen_to_ready": 15,     # part of 20
    "ready_to_shipped": 10,
}
STAGE_ORDER = list(STAGE_LABELS.keys())

def compute_breaches(row):
    stages = []
    a = diff_min(row["createdOn"], row["placedAt"])
    stages.append({"key":"created_to_placed","label":STAGE_LABELS["created_to_placed"],"threshold":THRESHOLDS["created_to_placed"],"duration":a,"breached":(a is not None and a>THRESHOLDS["created_to_placed"]),"segmentEnd":row["placedAt"]})
    b = diff_min(row["placedAt"], row["acceptedAt"])
    stages.append({"key":"placed_to_accepted","label":STAGE_LABELS["placed_to_accepted"],"threshold":THRESHOLDS["placed_to_accepted"],"duration":b,"breached":(b is not None and b>THRESHOLDS["placed_to_accepted"]),"segmentEnd":row["acceptedAt"]})
    c = diff_min(row["acceptedAt"], row["readyAt"])
    stages.append({"key":"accepted_to_in_kitchen","label":STAGE_LABELS["accepted_to_in_kitchen"],"threshold":THRESHOLDS["accepted_to_in_kitchen"],"duration":c,"breached":(c is not None and c>THRESHOLDS["accepted_to_in_kitchen"]),"segmentEnd":row["readyAt"]})
    stages.append({"key":"in_kitchen_to_ready","label":STAGE_LABELS["in_kitchen_to_ready"],"threshold":THRESHOLDS["in_kitchen_to_ready"],"duration":c,"breached":(c is not None and c>THRESHOLDS["in_kitchen_to_ready"]),"segmentEnd":row["readyAt"]})
    d = diff_min(row["readyAt"], row["shippedAt"])
    stages.append({"key":"ready_to_shipped","label":STAGE_LABELS["ready_to_shipped"],"threshold":THRESHOLDS["ready_to_shipped"],"duration":d,"breached":(d is not None and d>THRESHOLDS["ready_to_shipped"]),"segmentEnd":row["shippedAt"]})
    breached = [s for s in stages if s["breached"]]
    first_breach = None
    if breached:
        breached = sorted(breached, key=lambda s: (pd.Timestamp.min if pd.isna(s["segmentEnd"]) else s["segmentEnd"]))
        first_breach = breached[0]
    return stages, first_breach

# ---------- Upload ----------
with st.sidebar:
    st.markdown("### Upload Excel files (first sheet used)")
    orders_file = st.file_uploader("Orders workbook", type=["xlsx","xls"], key="orders")
    notes_file  = st.file_uploader("Notes workbook",  type=["xlsx","xls"], key="notes")

if not orders_file or not notes_file:
    st.info("Upload both **Orders** and **Notes** Excel files in the sidebar to begin.")
    st.stop()

# Read first sheet as-is (no assumptions about headers)
orders_df_raw = pd.read_excel(orders_file, sheet_name=0)
notes_df_raw  = pd.read_excel(notes_file,  sheet_name=0)

st.markdown("### 1) Map your columns")
with st.expander("Show detected columns", expanded=False):
    st.write("**Orders columns:**", list(orders_df_raw.columns))
    st.write("**Notes columns:**", list(notes_df_raw.columns))

# ---------- Column mapping UI ----------
st.markdown("**Orders mapping**")
oc1, oc2 = st.columns(2)
oc3, oc4 = st.columns(2)
oc5, oc6 = st.columns(2)

orders_cols = ["— Select —"] + [str(c) for c in orders_df_raw.columns]

order_id_col  = oc1.selectbox("Order ID column (join key)", orders_cols, index=0, key="oid")
created_col   = oc2.selectbox("Created On", orders_cols, index=0, key="ocreated")
placed_col    = oc3.selectbox("Order Placed Time", orders_cols, index=0, key="oplaced")
accepted_col  = oc4.selectbox("Order Accepted Time", orders_cols, index=0, key="oaccepted")
ready_col     = oc5.selectbox("Order Ready Time", orders_cols, index=0, key="oready")
shipped_col   = oc6.selectbox("Shipped At Date & Time", orders_cols, index=0, key="oshipped")

st.markdown("**Notes mapping**")
nc1, nc2, nc3 = st.columns(3)
notes_cols = ["— Select —"] + [str(c) for c in notes_df_raw.columns]
note_id_col   = nc1.selectbox("Notes: Order ID column (join key)", notes_cols, index=0, key="nid")
note_time_col = nc2.selectbox("Notes: Created at", notes_cols, index=0, key="ntime")
note_desc_col = nc3.selectbox("Notes: Description (optional)", notes_cols, index=0, key="ndesc")

# Validate mapping
missing = []
if order_id_col == "— Select —":  missing.append("Orders: Order ID")
if created_col  == "— Select —":  missing.append("Orders: Created On")
if placed_col   == "— Select —":  missing.append("Orders: Order Placed Time")
if accepted_col == "— Select —":  missing.append("Orders: Order Accepted Time")
if ready_col    == "— Select —":  missing.append("Orders: Order Ready Time")
if shipped_col  == "— Select —":  missing.append("Orders: Shipped At Date & Time")
if note_id_col  == "— Select —":  missing.append("Notes: Order ID")
if note_time_col== "— Select —":  missing.append("Notes: Created at")
# description optional

if missing:
    st.warning("Please map all required fields:\n\n- " + "\n- ".join(missing))
    st.stop()

# ---------- Build canonical data using mapping ----------
def build_orders(df):
    rows = []
    for _, r in df.iterrows():
        oid = r[order_id_col]
        if pd.isna(oid):
            continue
        rows.append({
            "id": str(oid).strip(),
            "createdOn": to_dt(r[created_col]),
            "placedAt":  to_dt(r[placed_col]),
            "acceptedAt":to_dt(r[accepted_col]),
            "readyAt":   to_dt(r[ready_col]),
            "shippedAt": to_dt(r[shipped_col]),
        })
    return pd.DataFrame(rows)

def build_notes(df):
    rows = []
    for _, r in df.iterrows():
        nid = r[note_id_col]
        if pd.isna(nid):
            continue
        rows.append({
            "id": str(nid).strip(),
            "noteAt": to_dt(r[note_time_col]),
            "description": "" if note_desc_col == "— Select —" else (r[note_desc_col] if pd.notna(r[note_desc_col]) else "")
        })
    return pd.DataFrame(rows)

orders = build_orders(orders_df_raw)
notes  = build_notes(notes_df_raw)

# Index/sort notes
notes = notes.sort_values("noteAt", na_position="first")
notes_by_id = notes.groupby("id")

# Enrich orders
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
        "createdOn": row["createdOn"],
        "placedAt": row["placedAt"],
        "acceptedAt": row["acceptedAt"],
        "readyAt": row["readyAt"],
        "shippedAt": row["shippedAt"],
        "notes": nb
    })

# ---------- 1) Metrics ----------
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

st.subheader("Metrics")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Orders", f"{len(orders)}")
c2.metric("Orders With Any Breach", f"{orders_with_breach}")
c3.metric("Orders Without Breach", f"{len(orders)-orders_with_breach}")
c4.metric("Total Breaches (All Stages)", f"{total_breaches}")

# ---------- 2) Breach Summary by Stage ----------
st.subheader("Breach Summary by Stage")
summary_df = pd.DataFrame([{
    "Stage": STAGE_LABELS[k],
    "Threshold (min)": THRESHOLDS[k],
    "Breached Count": counts_by_stage[k]
} for k in STAGE_ORDER])
st.dataframe(summary_df, use_container_width=True)
st.download_button("Download Summary CSV", summary_df.to_csv(index=False).encode("utf-8"),
                   file_name="breach_summary_by_stage.csv", mime="text/csv")

# ---------- 3) Order-Level Details (📊 Output Example) ----------
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
        "Note Description": str(note_desc) if note_desc is not None else ""
    |   ,  # <-- keep this line clean if you copy; it's just to avoid formatting glitches
        "Note Added Status": note_status
    })
out_df = pd.DataFrame(out_rows)
st.dataframe(out_df, use_container_width=True)
st.download_button("Download Output CSV", out_df.to_csv(index=False).encode("utf-8"),
                   file_name="order_level_output.csv", mime="text/csv")
