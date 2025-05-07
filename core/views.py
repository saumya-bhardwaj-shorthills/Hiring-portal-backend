import logging
import requests
import fitz  # PyMuPDF
from io import BytesIO
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.conf import settings
from .graph_utils import download_file
import re
from .models import SharePointSite, Candidate
from django.db.models import Q
import json
from .models import Candidate
from django.utils.crypto import get_random_string

logger = logging.getLogger(__name__)

@api_view(['POST'])
def get_site_id(request):
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return Response({"error": "No authorization header"}, status=400)
        access_token = auth_header.split(' ')[1]

        site_url = request.data.get('site_url')
        if not site_url:
            return Response({"error": "No site URL provided"}, status=400)

        # Extract hostname and path
        if '://' in site_url:
            site_url = site_url.split('://')[1]
        parts = site_url.split('/')
        hostname = parts[0]
        path = '/' + '/'.join(parts[1:])

        url = f'https://graph.microsoft.com/v1.0/sites/{hostname}:{path}'
        headers = {'Authorization': f'Bearer {access_token}'}

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        site_data = response.json()
        return Response({"site_id": site_data.get('id')})
    except Exception as e:
        logger.exception("Error fetching site ID")
        return Response({"error": str(e)}, status=500)

@api_view(['POST'])
def get_drives(request):
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return Response({"error": "No authorization header"}, status=400)
        access_token = auth_header.split(' ')[1]

        site_id = request.data.get('site_id')
        if not site_id:
            return Response({"error": "No site ID provided"}, status=400)

        url = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives'
        headers = {'Authorization': f'Bearer {access_token}'}

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        drives = response.json().get('value', [])
        return Response({"drives": drives})
    except Exception as e:
        logger.exception("Error fetching drives")
        return Response({"error": str(e)}, status=500)

@api_view(['POST'])
def fetch_resumes(request):
    try:
        access_token = request.headers.get('Authorization').split(' ')[1]
        site_id = request.data.get('site_id')
        drive_id = request.data.get('drive_id')

        # Step 1: Get the "Resume" folder metadata
        resume_folder_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/root:/Resume"
        folder_response = requests.get(resume_folder_url, headers={
            'Authorization': f'Bearer {access_token}'
        })
        folder_response.raise_for_status()
        folder_data = folder_response.json()
        folder_id = folder_data['id']

        # Step 2: List children (resumes) inside the "Resume" folder
        files_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/items/{folder_id}/children"
        files_response = requests.get(files_url, headers={
            'Authorization': f'Bearer {access_token}'
        })
        files_response.raise_for_status()
        files = files_response.json().get('value', [])
        return Response(files)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


def extract_text_from_pdf(pdf_bytes):
    text = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text()
    return text

@api_view(['POST'])
def parse_resume(request):
    file_id   = request.data.get('file_id')
    site_id   = request.data.get('site_id')
    drive_id  = request.data.get('drive_id')
    auth_hdr  = request.headers.get('Authorization')

    if not (file_id and site_id and drive_id and auth_hdr):
        return Response({"error": "Missing file_id, site_id, drive_id or auth"}, status=400)

    access_token = auth_hdr.split(' ')[1]

    try:
        # --- Download PDF ---
        url = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/items/{file_id}/content'
        headers = {'Authorization': f'Bearer {access_token}'}
        r = requests.get(url, headers=headers); r.raise_for_status()
        raw_pdf = r.content

        # --- Extract text ---
        resume_text = extract_text_from_pdf(BytesIO(raw_pdf))
        logger.debug(f"[RESUME TEXT]: {resume_text[:200]}...")

        # --- Fetch metadata (to get the sharepoint link) ---
        meta_url  = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/items/{file_id}'
        meta_resp = requests.get(meta_url, headers=headers); meta_resp.raise_for_status()
        web_url    = meta_resp.json().get('webUrl', '')

        # --- Build and call the LLM prompt ---
        prompt = f"""
Given the following resume text, return *only* a JSON object with exactly these fields:

1. name: string
2. email: string
3. phone_number: string
4. employment: array of objects, each with company, role, start_date, end_date, description
5. education: array of objects, each with institution, degree, start_date, end_date
6. skills: array of strings
7. profile_summary: string

Respond *only* with JSON.

Resume text:
\"\"\"
{resume_text}
\"\"\"
"""
        llm_resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.GEMINI_API_KEY}",
            json={"contents":[{"parts":[{"text":prompt}]}]},
            headers={'Content-Type':'application/json'}
        )
        llm_json = llm_resp.json()
        raw = llm_json['candidates'][0]['content']['parts'][0]['text']
        # strip markdown fences if any
        json_str = re.sub(r'^```json|```$', '', raw.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(json_str)

        # --- Create Candidate in DB ---
        candidate = Candidate.objects.create(
            file_id       = file_id,
            resume_url    = web_url,
            resume_id     = get_random_string(12),
            name          = parsed.get("name",""),
            email         = parsed.get("email",""),
            phone         = parsed.get("phone_number",""),
            profile_summary = parsed.get("profile_summary","") or "",
            parsed_data     = parsed
        )

        # --- Return the full Candidate record ---
        return Response({
            "id":            candidate.id,
            "file_id":       candidate.file_id,
            "resume_url":    candidate.resume_url,
            "resume_id":     candidate.resume_id,
            "name":          candidate.name,
            "email":         candidate.email,
            "phone":         candidate.phone,
            "profile_summary": candidate.profile_summary,
            "parsed_data":     candidate.parsed_data,
        })

    except Exception as e:
        logger.exception("Error in parse_resume")
        return Response({"error": str(e)}, status=500)



@api_view(['GET'])
def search_candidates(request):
    keyword = request.GET.get("keyword", "").lower()
    if not keyword:
        return Response({"error": "Keyword is required"}, status=400)

    qs = Candidate.objects.filter(Q(parsed_data__icontains=keyword))
    results = []
    for c in qs:
        pd = c.parsed_data or {}
        results.append({
            "id":               c.id,
            "name":             c.name,
            "email":            c.email,
            "phone":            c.phone,
            "resume_url":       c.resume_url,
            "skills":           pd.get("skills", {}),
            "profile_summary":  pd.get("profile_summary", "") or c.profile_summary,
        })
    return Response({"results": results})

@api_view(['GET'])
def list_candidates(request):
    """
    Return all persisted candidates with basic info.
    """
    candidates = Candidate.objects.all()
    data = []
    for c in candidates:
        pd = c.parsed_data or {}
        data.append({
            "id":               c.id,
            "name":             c.name,
            "email":            c.email,
            "phone":            c.phone,
            "resume_url":       c.resume_url,
            "skills":           pd.get("skills", {}),
            "profile_summary":  pd.get("profile_summary", "") or c.profile_summary,
        })
    return Response(data)

@api_view(['GET', 'POST'])
def sites(request):
    """List existing sites or add a new one."""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return Response({"error": "No authorization header"}, status=400)
    token = auth_header.split(' ')[1]

    if request.method == 'GET':
        qs = SharePointSite.objects.all()
        data = [
            {
                "id": s.id,
                "site_url": s.site_url,
                "site_id": s.site_id,
                "drive_id": s.drive_id
            }
            for s in qs
        ]
        return Response(data)

    # POST: add new site
    site_url = request.data.get('site_url')
    if not site_url:
        return Response({"error": "site_url required"}, status=400)

    # 1) Fetch site_id
    # reuse your logic from get_site_id
    if '://' in site_url:
        host_and_path = site_url.split('://')[1]
    else:
        host_and_path = site_url
    parts = host_and_path.split('/')
    hostname = parts[0]
    path = '/' + '/'.join(parts[1:])
    url = f'https://graph.microsoft.com/v1.0/sites/{hostname}:{path}'
    headers = {'Authorization': f'Bearer {token}'}
    resp = requests.get(url, headers=headers); resp.raise_for_status()
    site_data = resp.json()
    site_id = site_data['id']

    # 2) Fetch drives and pick the first one
    drives_url = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives'
    drives = requests.get(drives_url, headers=headers).json().get('value', [])
    if not drives:
        return Response({"error": "No drives found"}, status=400)
    drive_id = drives[0]['id']

    # 3) Save
    site_obj, created = SharePointSite.objects.get_or_create(
        site_url=site_url,
        defaults={"site_id": site_id, "drive_id": drive_id}
    )

    return Response({
        "id": site_obj.id,
        "site_url": site_obj.site_url,
        "site_id": site_obj.site_id,
        "drive_id": site_obj.drive_id
    })


@api_view(['GET'])
def fetch_site_resumes(request, pk):
    """Return only the unparsed resumes for the given saved site."""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return Response({"error": "No authorization header"}, status=400)
    token = auth_header.split(' ')[1]

    try:
        site = SharePointSite.objects.get(pk=pk)
    except SharePointSite.DoesNotExist:
        return Response({"error": "Site not found"}, status=404)

    # 1) Locate the 'Resume' folder
    resume_folder_url = (
        f"https://graph.microsoft.com/v1.0/sites/{site.site_id}"
        f"/drives/{site.drive_id}/root:/Resume"
    )
    headers = {'Authorization': f'Bearer {token}'}
    folder = requests.get(resume_folder_url, headers=headers)
    folder.raise_for_status()
    folder_id = folder.json()['id']

    # 2) List children
    children_url = (
        f"https://graph.microsoft.com/v1.0/sites/{site.site_id}"
        f"/drives/{site.drive_id}/items/{folder_id}/children"
    )
    files = requests.get(children_url, headers=headers).json().get('value', [])

    # 3) Filter out already parsed
    parsed_ids = Candidate.objects.values_list('file_id', flat=True)
    unparsed = [f for f in files if f['id'] not in parsed_ids]

    return Response(unparsed)
