# Water & Wastewater Sampling and Lab Compliance App

A Persian (RTL) Streamlit app for environmental water/wastewater sampling and lab-result compliance checking against Iranian Department of Environment (DOE) standards.

## Features
- User registration and login (PBKDF2-SHA256, per-user salt, login throttling)
- Sample registration with an interactive satellite map (click to set coordinates), Jalali dates, Tehran time
- Lab-result entry for 28 parameters in 6 groups, evaluated against three categories: surface-water discharge, agricultural use, and absorbing wells
- Status per parameter: pass / near limit / fail / informational / not measured, plus overall verdict
- Two Persian PDF reports (sampling report and lab-result report) with satellite image or map link
- Per-user data isolation (every query filtered by `user_id`), SQLite with cascade delete

## Run locally
```
pip install -r requirements.txt
streamlit run app.py
```

## Deploy (free, works on phones and desktop browsers)
1. Push this repo to GitHub.
2. Go to https://share.streamlit.io, click **Create app**, pick this repo, branch `main`, main file `app.py`.
3. Deploy. The resulting `https://<name>.streamlit.app` link can be shared with anyone.

## Notes
- SQLite storage is ephemeral on Streamlit Community Cloud: data is lost on restart/redeploy. Use an external database (e.g. Supabase/Postgres) for persistence.
- Some limits (mercury, EC, TDS) are approximate guide values. Results are indicative only and do not replace an official laboratory opinion.
- Fonts: Vazirmatn (SIL OFL).

## Structure
`app.py` UI and routing · `database.py` SQLite layer · `standards.py` limits and evaluation · `pdf_generator.py` PDF reports · `utils.py` Jalali dates and digits
