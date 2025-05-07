
````markdown
# ATS Backend

This is the Django‐based backend for the AI­-powered resume parser and recruiter portal. It exposes a set of REST endpoints for:

- Authenticating to SharePoint via Microsoft Graph  
- Fetching resumes from one or more SharePoint sites  
- Parsing resumes with Google Gemini LLM  
- Storing and searching parsed candidate data  

---

## 🚀 Project Setup

1. **Clone the repo**  
   ```bash
   git clone https://your-repo-url.git
   cd Parser/backend
````

2. **Create & activate a virtualenv**

   ```bash
   python3 -m venv env
   source env/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   Copy `.env.example` → `.env` and fill in:

   ```ini
   SECRET_KEY=your_django_secret_key
   GEMINI_API_KEY=your_google_gemini_api_key
   TENANT_ID=""
   CLIENT_ID=""
   CLIENT_SECRET=your-client-secret
   ```

5. **Prepare the database**
   If you’re starting fresh (no existing `db.sqlite3`):

   ```bash
   rm db.sqlite3            # optional: destroy old DB if present
   python manage.py makemigrations
   python manage.py migrate
   ```

   Otherwise, to sync new tables without wiping data:

   ```bash
   python manage.py migrate --run-syncdb
   ```

6. **Run the dev server**

   ```bash
   python manage.py runserver
   ```

   The API will be live at `http://localhost:8000/`

---

## 🔗 API Endpoints

All endpoints live under `/api/...` and expect a Bearer token (Microsoft Graph access token) in the `Authorization` header, e.g.:

```
Authorization: Bearer eyJ0eXAiOiJK...
```

### Site & Drive Discovery

* **`POST /api/get-site-id/`**
  Request body: `{ "site_url": "https://contoso.sharepoint.com/sites/HR" }`
  → Returns `{ "site_id": "<GUID>" }`

* **`POST /api/get-drives/`**
  Request body: `{ "site_id": "<GUID>" }`
  → Returns `{ "drives": [ { "id": "...", "name": "Documents" }, … ] }`

### SharePoint Sites Management

* **`GET /api/sites/`**
  → List saved SharePoint sites (id, site\_url, site\_id, drive\_id)

* **`POST /api/sites/`**
  Request body: `{ "site_url": "https://…/sites/XYZ" }`
  → Saves a new site (fetches its site\_id & first drive\_id) and returns its record

* **`GET /api/sites/{pk}/resumes/`**
  → Lists only the **unparsed** resumes in the “Resume” folder of that saved site

### Resume Fetch & Parse

* **`POST /api/fetch-resumes/`**
  Body: `{ "site_id": "...", "drive_id": "..." }`
  → Lists *all* files under `/root:/Resume:/children`

* **`POST /api/parse-resume/`**
  Body:

  ```json
  {
    "file_id":   "<GraphItemID>",
    "site_id":   "<GUID>",
    "drive_id":  "<GUID>"
  }
  ```

  →

  1. Downloads the PDF
  2. Extracts text via PyMuPDF
  3. Calls Gemini to produce structured JSON (name, email, phone, employment, education, skills, profile\_summary)
  4. Persists a `Candidate` record (including `resume_url`)
  5. Returns the full saved record:

  ```json
  {
    "id": 1,
    "file_id": "...",
    "resume_url": "https://…",
    "resume_id": "xYz123",
    "name": "Alice",
    "email": "alice@example.com",
    "phone": "123-456-7890",
    "profile_summary": "…",
    "parsed_data": { /* full JSON from LLM */ }
  }
  ```

### Candidate Search & Listing

* **`GET /api/candidates/`**
  → Returns all saved candidates:

  ```json
  [
    { "id":1,"name":"Alice",…,"skills":{…},"profile_summary":"…"},
    …
  ]
  ```

* **`GET /api/search-candidates/?keyword=php`**
  → Returns only those whose parsed\_data contains “php” (case-insensitive)

---

## 📂 Folder Structure

```
backend/
├── config/                   # Django project settings
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py               # includes core.urls
│   └── wsgi.py
├── core/                     # Main app
│   ├── migrations/           # Django migrations
│   ├── __init__.py
│   ├── models.py             # SharePointSite, Candidate
│   ├── views.py              # all API view functions
│   ├── urls.py               # path('api/...') → views
│   └── graph_utils.py        # helper to download files, tokens
├── db.sqlite3                # local SQLite database
├── env/                      # Python virtualenv
├── manage.py                 # Django CLI
└── requirements.txt          # pip-installable deps
```
