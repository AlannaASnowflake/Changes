import streamlit as st
import sqlite3
import os
import io
import re
import smtplib
from email.mime.text import MIMEText
import pandas as pd
from datetime import datetime, timedelta, date, timezone

# ---------------------------------------------------------------------------
# Configuration — UPDATE THESE FOR YOUR ENVIRONMENT
# ---------------------------------------------------------------------------
# Email settings for expedited change notifications
SMTP_SERVER = "smtp.gmail.com"          # Your SMTP server
SMTP_PORT = 587                          # TLS port
SMTP_USER = "your_email@gmail.com"       # Sender email
SMTP_PASSWORD = ""                       # App password (use env var in prod)
NOTIFICATION_EMAIL = "your_email@gmail.com"  # Recipient for expedited alerts

DB_PATH = "change_submissions.db"        # SQLite database file

POD_NAMES = [
    "Platform Engineering",
    "Data Engineering",
    "Analytics",
    "DevOps",
    "Security",
    "Infrastructure",
]

ENVIRONMENTS = ["UAT", "PROD"]

STATUSES = ["SUBMITTED", "UNDER REVIEW", "APPROVED", "REJECTED"]

STATUS_COLORS = {
    "SUBMITTED": "#808080",
    "UNDER REVIEW": "#DAA520",
    "APPROVED": "#2E8B57",
    "REJECTED": "#DC3545",
}

CST_CUTOFF_HOUR = 12
WEEKLY_CHANGE_LIMIT = 2

TIME_RANGE_OPTIONS = ["All Time", "Past Week", "Past Month", "Custom Range"]

CST = timezone(timedelta(hours=-6))


# ---------------------------------------------------------------------------
# Database setup (SQLite)
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS CHANGE_SUBMISSIONS (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            POD_NAME TEXT,
            CHG_NUMBER TEXT,
            IS_EXPEDITED INTEGER DEFAULT 0,
            EXPEDITED_JUSTIFICATION TEXT,
            STATUS TEXT DEFAULT 'SUBMITTED',
            SUBMITTED_AT TEXT,
            EXPECTED_REVIEW_DATE TEXT,
            REVIEWED_BY TEXT,
            REVIEWED_AT TEXT,
            NOTES TEXT,
            IS_STANDARD INTEGER DEFAULT 0,
            VOLUME_JUSTIFICATION TEXT,
            ENVIRONMENT TEXT DEFAULT 'UAT',
            ADDITIONAL_NOTES TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_cst():
    return datetime.now(CST)


def get_expected_review_date(cst_now):
    cst_date = cst_now.date()
    cst_hour = cst_now.hour
    weekday = cst_date.weekday()

    if weekday >= 5:
        days_until_monday = 7 - weekday
        return cst_date + timedelta(days=days_until_monday)

    if cst_hour < CST_CUTOFF_HOUR:
        return cst_date
    else:
        next_day = cst_date + timedelta(days=1)
        if next_day.weekday() >= 5:
            days_until_monday = 7 - next_day.weekday()
            return next_day + timedelta(days=days_until_monday)
        return next_day


def get_weekly_count(pod, environment):
    conn = get_db()
    week_start = (
        datetime.now(CST) - timedelta(days=datetime.now(CST).weekday())
    ).strftime("%Y-%m-%d")
    row = conn.execute(
        """SELECT COUNT(*) AS CNT FROM CHANGE_SUBMISSIONS
        WHERE POD_NAME = ? AND ENVIRONMENT = ?
          AND IS_STANDARD = 0 AND IS_EXPEDITED = 0
          AND SUBMITTED_AT >= ?""",
        (pod, environment, week_start),
    ).fetchone()
    conn.close()
    return row["CNT"] if row else 0


def send_expedited_email(chg_number, pod_name, justification):
    if not SMTP_PASSWORD:
        st.warning("Email not configured — set SMTP_PASSWORD to enable notifications.")
        return False
    subject = f"EXPEDITED Change Submitted: {chg_number} ({pod_name})"
    body = (
        f"An expedited change has been submitted.\n\n"
        f"CHG Number: {chg_number}\n"
        f"Pod: {pod_name}\n"
        f"Justification: {justification}\n\n"
        f"Please review this change as soon as possible."
    )
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = NOTIFICATION_EMAIL
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        st.warning(f"Email notification failed: {e}")
        return False


def format_timestamp(val):
    if not val or pd.isna(val):
        return ""
    s = str(val)
    s = re.sub(r"\s*[+-]\d{2}:?\d{2}\s*$", "", s)
    s = re.sub(r"\.\d+", "", s)
    return s


def generate_spreadsheet(df):
    cols = [
        "CHG_NUMBER", "POD_NAME", "ENVIRONMENT", "IS_STANDARD", "IS_EXPEDITED",
        "STATUS", "SUBMITTED_AT", "EXPECTED_REVIEW_DATE", "ADDITIONAL_NOTES",
    ]
    export_df = df[[c for c in cols if c in df.columns]].copy()
    names = [
        "CHG Number", "Pod", "Environment", "Standard", "Expedited",
        "Status", "Submitted Date/Time", "Expected Review Day", "Additional Notes",
    ]
    export_df.columns = names[: len(export_df.columns)]
    export_df["CHG Number"] = export_df["CHG Number"].str.upper()
    if "Submitted Date/Time" in export_df.columns:
        export_df["Submitted Date/Time"] = export_df["Submitted Date/Time"].apply(
            format_timestamp
        )
    return export_df.to_csv(index=False).encode("utf-8")


def load_submissions():
    conn = get_db()
    df = pd.read_sql_query(
        "SELECT * FROM CHANGE_SUBMISSIONS ORDER BY SUBMITTED_AT DESC", conn
    )
    conn.close()
    if not df.empty and "CHG_NUMBER" in df.columns:
        df["CHG_NUMBER"] = df["CHG_NUMBER"].str.upper()
    # SQLite stores booleans as 0/1
    for col in ("IS_STANDARD", "IS_EXPEDITED"):
        if col in df.columns:
            df[col] = df[col].astype(bool)
    return df


def color_status(status):
    color = STATUS_COLORS.get(status, "#808080")
    return (
        f'<span style="background-color:{color};color:white;padding:3px 10px;'
        f'border-radius:4px;font-weight:bold;font-size:0.85em">{status}</span>'
    )


def render_styled_table(df, columns):
    display = df[columns].copy()
    if "SUBMITTED_AT" in display.columns:
        display["SUBMITTED_AT"] = display["SUBMITTED_AT"].apply(format_timestamp)

    header_map = {
        "CHG_NUMBER": "CHG Number", "POD_NAME": "Pod", "ENVIRONMENT": "Env",
        "IS_STANDARD": "Standard", "IS_EXPEDITED": "Expedited",
        "STATUS": "Status", "SUBMITTED_AT": "Submitted",
        "EXPECTED_REVIEW_DATE": "Review Date",
    }
    headers = [header_map.get(c, c) for c in columns]

    html = '<table style="width:100%;border-collapse:collapse;font-size:0.9em">'
    html += "<thead><tr>"
    for h in headers:
        html += (
            f'<th style="text-align:left;padding:8px 12px;'
            f'border-bottom:2px solid #444">{h}</th>'
        )
    html += "</tr></thead><tbody>"

    for _, row in display.iterrows():
        html += "<tr>"
        for col in columns:
            val = row[col]
            if col == "STATUS":
                cell = color_status(str(val))
            elif col in ("IS_STANDARD", "IS_EXPEDITED"):
                cell = "Yes" if val else "No"
            else:
                cell = str(val) if val and not pd.isna(val) else ""
            html += f'<td style="padding:6px 12px;border-bottom:1px solid #333">{cell}</td>'
        html += "</tr>"
    html += "</tbody></table>"
    return html


def render_change_info(row):
    env_label = row.get("ENVIRONMENT", "")
    st.markdown(f"**Environment:** {env_label}")
    st.markdown(f"**Submitted at:** {format_timestamp(row['SUBMITTED_AT'])}")
    st.markdown(f"**Expected review:** {row['EXPECTED_REVIEW_DATE']}")
    st.markdown(f"**Standard:** {'Yes' if row['IS_STANDARD'] else 'No'}")
    if row["IS_EXPEDITED"] and row.get("EXPEDITED_JUSTIFICATION"):
        st.markdown(f"**Expedited justification:** {row['EXPEDITED_JUSTIFICATION']}")
    if row.get("VOLUME_JUSTIFICATION"):
        st.markdown(f"**Volume justification:** {row['VOLUME_JUSTIFICATION']}")
    if row.get("ADDITIONAL_NOTES"):
        st.markdown(f"**Additional notes:** {row['ADDITIONAL_NOTES']}")
    if row.get("REVIEWED_BY"):
        st.markdown(f"**Reviewed by:** {row['REVIEWED_BY']}")
    if row.get("NOTES"):
        st.markdown(f"**Review notes:** {row['NOTES']}")


def filter_by_date_range(df, time_range, start_date=None, end_date=None):
    if df.empty or "SUBMITTED_AT" not in df.columns:
        return df
    ts = pd.to_datetime(df["SUBMITTED_AT"], errors="coerce")
    today = pd.Timestamp.now()
    if time_range == "Past Week":
        mask = ts >= (today - pd.Timedelta(days=7))
    elif time_range == "Past Month":
        mask = ts >= (today - pd.Timedelta(days=30))
    elif time_range == "Custom Range" and start_date and end_date:
        mask = (ts >= pd.Timestamp(start_date)) & (
            ts < pd.Timestamp(end_date) + pd.Timedelta(days=1)
        )
    else:
        return df
    return df[mask]


# ---------------------------------------------------------------------------
# App layout
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Change Submissions", page_icon=":clipboard:", layout="wide"
)
st.title("Change Submission Tracker")

tab_submit, tab_admin = st.tabs(["Submit Change", "Admin Review"])

TABLE_COLUMNS = [
    "CHG_NUMBER", "POD_NAME", "ENVIRONMENT", "IS_STANDARD",
    "IS_EXPEDITED", "STATUS", "SUBMITTED_AT", "EXPECTED_REVIEW_DATE",
]

# ---------------------------------------------------------------------------
# Tab 1: Submit a Change
# ---------------------------------------------------------------------------
with tab_submit:
    st.subheader("Submit a New Change")

    rc = st.session_state.get("reset_counter", 0)

    col_pre1, col_pre2 = st.columns(2)
    with col_pre1:
        pod_name = st.selectbox(
            "Pod / Team", ["{Select}"] + POD_NAMES, key=f"pod_select_{rc}"
        )
    with col_pre2:
        environment = st.selectbox(
            "Environment", ["{Select}"] + ENVIRONMENTS, key=f"env_select_{rc}"
        )

    if pod_name != "{Select}" and environment != "{Select}":
        weekly_count = get_weekly_count(pod_name, environment)
        over_limit = weekly_count >= WEEKLY_CHANGE_LIMIT
    else:
        weekly_count = 0
        over_limit = False

    if over_limit:
        st.warning(
            f"**{pod_name}** already has **{weekly_count}** regular {environment} "
            f"change(s) this week (limit: {WEEKLY_CHANGE_LIMIT}). "
            f"Standard and expedited changes do not count toward this limit. "
            f"A justification is required to submit another regular change."
        )

    col_check1, col_check2 = st.columns(2)
    with col_check1:
        is_standard = st.checkbox("Standard change", key=f"std_check_{rc}")
    with col_check2:
        is_expedited = st.checkbox("Expedited change", key=f"exp_check_{rc}")

    justification = ""
    if is_expedited:
        justification = st.text_area(
            "Expedited Justification (required — MUST be high risk)",
            placeholder="Explain why this change needs to be expedited. "
            "Expedited changes MUST be high risk...",
            key=f"exp_justification_{rc}",
        )

    volume_justification = ""
    if over_limit and not is_standard and not is_expedited:
        volume_justification = st.text_area(
            f"Volume Justification (required - over {WEEKLY_CHANGE_LIMIT} "
            f"regular {environment} changes this week)",
            placeholder=f"Explain why {pod_name} needs more than "
            f"{WEEKLY_CHANGE_LIMIT} regular {environment} changes this week...",
            key=f"vol_justification_{rc}",
        )

    additional_notes = st.text_area(
        "Additional Notes (optional)",
        placeholder="Any extra info DRE team should know for review "
        "(e.g. testing not done because data is not available in QA, "
        "KB does not exist because process/job not deployed to PROD, "
        "unusual time window needed, etc)",
        key=f"additional_notes_{rc}",
    )

    with st.form(f"change_form_{rc}", clear_on_submit=True):
        chg_number = st.text_input(
            "CHG Number (required — format: CHG-#####)",
            placeholder="CHG-12345",
            max_chars=10,
        )
        submitted = st.form_submit_button("Submit Change", type="primary")

    if submitted:
        errors = []
        if pod_name == "{Select}":
            errors.append("Please select a Pod / Team.")
        if environment == "{Select}":
            errors.append("Please select an Environment.")
        chg_stripped = chg_number.strip().upper()
        if not chg_stripped:
            errors.append("CHG Number is required.")
        elif not re.match(r"^CHG-\d{5}$", chg_stripped):
            errors.append(
                "CHG Number must be in the format CHG-##### (e.g. CHG-12345)."
            )
        else:
            db = get_db()
            dup = db.execute(
                "SELECT COUNT(*) AS CNT FROM CHANGE_SUBMISSIONS WHERE CHG_NUMBER = ?",
                (chg_stripped,),
            ).fetchone()
            db.close()
            if dup["CNT"] > 0:
                errors.append(f"Change **{chg_stripped}** has already been submitted.")
        if is_expedited and not justification.strip():
            errors.append(
                "Justification is required for expedited changes (MUST be high risk)."
            )
        if over_limit and not is_standard and not is_expedited:
            if not volume_justification.strip():
                errors.append(
                    f"Volume justification is required — {pod_name} has exceeded "
                    f"{WEEKLY_CHANGE_LIMIT} regular {environment} changes this week."
                )

        if errors:
            for err in errors:
                st.error(err)
        else:
            now_cst_time = now_cst()
            review_date = get_expected_review_date(now_cst_time)
            cst_timestamp = now_cst_time.strftime("%Y-%m-%d %H:%M:%S")

            db = get_db()
            db.execute(
                """INSERT INTO CHANGE_SUBMISSIONS
                    (POD_NAME, CHG_NUMBER, ENVIRONMENT, IS_STANDARD, IS_EXPEDITED,
                     EXPEDITED_JUSTIFICATION, VOLUME_JUSTIFICATION, STATUS,
                     EXPECTED_REVIEW_DATE, ADDITIONAL_NOTES, SUBMITTED_AT)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', ?, ?, ?)""",
                (
                    pod_name,
                    chg_stripped,
                    environment,
                    int(is_standard),
                    int(is_expedited),
                    justification.strip() if is_expedited else None,
                    volume_justification.strip()
                    if over_limit and not is_standard and not is_expedited
                    else None,
                    review_date.isoformat(),
                    additional_notes.strip() if additional_notes.strip() else None,
                    cst_timestamp,
                ),
            )
            db.commit()
            db.close()

            st.session_state["last_submitted"] = chg_stripped
            st.session_state["last_env"] = environment
            st.session_state["last_review_date"] = review_date.strftime("%B %d, %Y")
            st.session_state["last_expedited"] = is_expedited

            if is_expedited:
                send_expedited_email(chg_stripped, pod_name, justification)
                st.session_state["last_expedited_sent"] = True
            else:
                st.session_state["last_expedited_sent"] = False

            st.session_state["reset_counter"] = rc + 1
            st.rerun()

    if "last_submitted" in st.session_state:
        chg = st.session_state.pop("last_submitted")
        env = st.session_state.pop("last_env")
        rd = st.session_state.pop("last_review_date")
        was_expedited = st.session_state.pop("last_expedited")
        email_sent = st.session_state.pop("last_expedited_sent")
        st.success(
            f"Change **{chg}** ({env}) submitted! "
            f"Expected review date: **{rd}**"
        )
        if was_expedited and email_sent:
            st.info("Expedited notification email sent.")

    st.divider()
    st.subheader("Recent Submissions")
    df = load_submissions()
    if df.empty:
        st.info("No submissions yet.")
    else:
        st.markdown(
            render_styled_table(df, TABLE_COLUMNS), unsafe_allow_html=True
        )

# ---------------------------------------------------------------------------
# Tab 2: Admin Review
# ---------------------------------------------------------------------------
with tab_admin:
    st.subheader("Review & Update Submissions")

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        status_filter = st.multiselect(
            "Filter by Status", STATUSES, default=STATUSES
        )
    with col_f2:
        pod_filter = st.multiselect("Filter by Pod", POD_NAMES)
    with col_f3:
        env_filter = st.multiselect("Filter by Environment", ENVIRONMENTS)

    time_range = st.radio(
        "Time Range", TIME_RANGE_OPTIONS, horizontal=True, index=0
    )

    custom_start = None
    custom_end = None
    if time_range == "Custom Range":
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            custom_start = st.date_input(
                "Start Date", value=date.today() - timedelta(days=7)
            )
        with col_d2:
            custom_end = st.date_input("End Date", value=date.today())

    all_df = load_submissions()

    if all_df.empty:
        st.info("No submissions to review.")
    else:
        filtered = all_df.copy()
        if status_filter:
            filtered = filtered[filtered["STATUS"].isin(status_filter)]
        if pod_filter:
            filtered = filtered[filtered["POD_NAME"].isin(pod_filter)]
        if env_filter:
            filtered = filtered[filtered["ENVIRONMENT"].isin(env_filter)]
        filtered = filter_by_date_range(
            filtered, time_range, custom_start, custom_end
        )

        if filtered.empty:
            st.info("No submissions match the selected filters.")
        else:
            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                st.download_button(
                    "Download All Changes (CSV)",
                    data=generate_spreadsheet(all_df),
                    file_name="change_submissions_all.csv",
                    mime="text/csv",
                )
            with col_dl2:
                st.download_button(
                    "Download Filtered Changes (CSV)",
                    data=generate_spreadsheet(filtered),
                    file_name="change_submissions_filtered.csv",
                    mime="text/csv",
                )

            st.markdown(
                render_styled_table(filtered, TABLE_COLUMNS),
                unsafe_allow_html=True,
            )

            submitted_df = filtered[filtered["STATUS"] == "SUBMITTED"]
            under_review_df = filtered[filtered["STATUS"] == "UNDER REVIEW"]
            closed_df = filtered[
                filtered["STATUS"].isin(["APPROVED", "REJECTED"])
            ]

            today_str = str(date.today())
            if not submitted_df.empty:
                review_dates = submitted_df["EXPECTED_REVIEW_DATE"].astype(str)
                is_today = review_dates == today_str
                is_priority = (
                    submitted_df["IS_EXPEDITED"] | submitted_df["IS_STANDARD"]
                )
                needs_review_today = submitted_df[is_today | is_priority]
                awaiting_future = submitted_df[~is_today & ~is_priority]
            else:
                needs_review_today = submitted_df
                awaiting_future = submitted_df

            # --- Section 1: Needs Review Today ---
            st.divider()
            st.subheader("Submitted — Needs Review Today")
            if needs_review_today.empty:
                st.info("No changes need review today.")
            else:
                for _, row in needs_review_today.iterrows():
                    badges = []
                    if row["IS_EXPEDITED"]:
                        badges.append(":red[EXPEDITED]")
                    if row["IS_STANDARD"]:
                        badges.append(":blue[STANDARD]")
                    badge_str = (" " + " ".join(badges)) if badges else ""
                    with st.expander(
                        f"{row['CHG_NUMBER']} — {row['POD_NAME']} — "
                        f"{row.get('ENVIRONMENT', '')}{badge_str}"
                    ):
                        col_info, col_action = st.columns([2, 1])
                        with col_info:
                            render_change_info(row)
                        with col_action:
                            new_status = st.selectbox(
                                "Update Status", STATUSES, index=0,
                                key=f"status_{row['ID']}",
                            )
                            reviewer = st.text_input(
                                "Reviewer", key=f"reviewer_{row['ID']}"
                            )
                            notes = st.text_input(
                                "Notes", key=f"notes_{row['ID']}"
                            )
                            if st.button("Save", key=f"save_{row['ID']}", type="primary"):
                                db = get_db()
                                db.execute(
                                    """UPDATE CHANGE_SUBMISSIONS
                                    SET STATUS = ?, REVIEWED_BY = ?,
                                        REVIEWED_AT = ?, NOTES = ?
                                    WHERE ID = ?""",
                                    (
                                        new_status,
                                        reviewer.strip() if reviewer else None,
                                        now_cst().strftime("%Y-%m-%d %H:%M:%S"),
                                        notes.strip() if notes else None,
                                        row["ID"],
                                    ),
                                )
                                db.commit()
                                db.close()
                                st.success(f"{row['CHG_NUMBER']} updated to **{new_status}**.")
                                st.rerun()

            # --- Section 2: Awaiting Review (next business day) ---
            st.divider()
            st.subheader("Submitted — Awaiting Review (next business day)")
            if awaiting_future.empty:
                st.info("No submitted changes awaiting future review.")
            else:
                for _, row in awaiting_future.iterrows():
                    badges = []
                    if row["IS_EXPEDITED"]:
                        badges.append(":red[EXPEDITED]")
                    if row["IS_STANDARD"]:
                        badges.append(":blue[STANDARD]")
                    badge_str = (" " + " ".join(badges)) if badges else ""
                    with st.expander(
                        f"{row['CHG_NUMBER']} — {row['POD_NAME']} — "
                        f"{row.get('ENVIRONMENT', '')}{badge_str}"
                    ):
                        col_info, col_action = st.columns([2, 1])
                        with col_info:
                            render_change_info(row)
                        with col_action:
                            new_status = st.selectbox(
                                "Update Status", STATUSES, index=0,
                                key=f"status_{row['ID']}",
                            )
                            reviewer = st.text_input(
                                "Reviewer", key=f"reviewer_{row['ID']}"
                            )
                            notes = st.text_input(
                                "Notes", key=f"notes_{row['ID']}"
                            )
                            if st.button("Save", key=f"save_{row['ID']}", type="primary"):
                                db = get_db()
                                db.execute(
                                    """UPDATE CHANGE_SUBMISSIONS
                                    SET STATUS = ?, REVIEWED_BY = ?,
                                        REVIEWED_AT = ?, NOTES = ?
                                    WHERE ID = ?""",
                                    (
                                        new_status,
                                        reviewer.strip() if reviewer else None,
                                        now_cst().strftime("%Y-%m-%d %H:%M:%S"),
                                        notes.strip() if notes else None,
                                        row["ID"],
                                    ),
                                )
                                db.commit()
                                db.close()
                                st.success(f"{row['CHG_NUMBER']} updated to **{new_status}**.")
                                st.rerun()

            # --- Section 3: Under Review ---
            st.divider()
            st.subheader("Under Review")
            if under_review_df.empty:
                st.info("No changes currently under review.")
            else:
                for _, row in under_review_df.iterrows():
                    badges = []
                    if row["IS_EXPEDITED"]:
                        badges.append(":red[EXPEDITED]")
                    if row["IS_STANDARD"]:
                        badges.append(":blue[STANDARD]")
                    badge_str = (" " + " ".join(badges)) if badges else ""
                    with st.expander(
                        f"{row['CHG_NUMBER']} — {row['POD_NAME']} — "
                        f"{row.get('ENVIRONMENT', '')}{badge_str}"
                    ):
                        col_info, col_action = st.columns([2, 1])
                        with col_info:
                            render_change_info(row)
                        with col_action:
                            new_status = st.selectbox(
                                "Update Status", STATUSES, index=1,
                                key=f"status_{row['ID']}",
                            )
                            reviewer = st.text_input(
                                "Reviewer", key=f"reviewer_{row['ID']}"
                            )
                            notes = st.text_input(
                                "Notes", key=f"notes_{row['ID']}"
                            )
                            if st.button("Save", key=f"save_{row['ID']}", type="primary"):
                                db = get_db()
                                db.execute(
                                    """UPDATE CHANGE_SUBMISSIONS
                                    SET STATUS = ?, REVIEWED_BY = ?,
                                        REVIEWED_AT = ?, NOTES = ?
                                    WHERE ID = ?""",
                                    (
                                        new_status,
                                        reviewer.strip() if reviewer else None,
                                        now_cst().strftime("%Y-%m-%d %H:%M:%S"),
                                        notes.strip() if notes else None,
                                        row["ID"],
                                    ),
                                )
                                db.commit()
                                db.close()
                                st.success(f"{row['CHG_NUMBER']} updated to **{new_status}**.")
                                st.rerun()

            # --- Section 4: Approved / Rejected (read-only) ---
            st.divider()
            st.subheader("Approved / Rejected")
            if closed_df.empty:
                st.info("No approved or rejected changes in this view.")
            else:
                for _, row in closed_df.iterrows():
                    badges = []
                    if row["IS_EXPEDITED"]:
                        badges.append(":red[EXPEDITED]")
                    if row["IS_STANDARD"]:
                        badges.append(":blue[STANDARD]")
                    status_badge = (
                        ":green[APPROVED]"
                        if row["STATUS"] == "APPROVED"
                        else ":red[REJECTED]"
                    )
                    badges.append(status_badge)
                    badge_str = " " + " ".join(badges)
                    with st.expander(
                        f"{row['CHG_NUMBER']} — {row['POD_NAME']} — "
                        f"{row.get('ENVIRONMENT', '')}{badge_str}"
                    ):
                        render_change_info(row)
