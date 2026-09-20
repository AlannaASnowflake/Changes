# Change Submission Tracker — Standalone Version

This version runs outside Snowflake on any machine with Python 3.9+.

## Setup

```bash
pip install -r requirements.txt
```

## Configure Email (optional)

Edit the top of `streamlit_app.py` and set:

```python
SMTP_SERVER = "smtp.gmail.com"       # Your mail server
SMTP_PORT = 587
SMTP_USER = "you@gmail.com"          # Sender
SMTP_PASSWORD = "your-app-password"  # Gmail app password or SMTP password
NOTIFICATION_EMAIL = "you@gmail.com" # Recipient for expedited alerts
```

For Gmail, generate an App Password at https://myaccount.google.com/apppasswords.

If you leave `SMTP_PASSWORD` empty, the app works normally but skips email.

## Run

```bash
streamlit run streamlit_app.py
```

The app creates a local `change_submissions.db` SQLite file in the same directory. No Snowflake account needed.

## Share

To let others access it:
- **Local network**: Run with `streamlit run streamlit_app.py --server.address 0.0.0.0` and share your IP
- **Internet**: Deploy to [Streamlit Community Cloud](https://streamlit.io/cloud) (free) or any VM/container host
- **Streamlit Cloud**: Push to a GitHub repo, connect at share.streamlit.io, and anyone with the URL can use it
