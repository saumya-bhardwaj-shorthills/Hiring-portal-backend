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
from docx import Document  # python-docx for .docx

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


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    text = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text()
    return text

def extract_text_from_docx(docx_bytes: bytes) -> str:
    doc = Document(BytesIO(docx_bytes))
    return "\n".join(p.text for p in doc.paragraphs)

@api_view(['POST'])
def parse_resume(request):
    file_id = request.data.get('file_id')
    site_id = request.data.get('site_id')
    drive_id = request.data.get('drive_id')
    if not (file_id and site_id and drive_id):
        return Response({"error": "File ID, Site ID, and Drive ID are required"}, status=400)

    auth = request.headers.get('Authorization')
    if not auth:
        return Response({"error": "No authorization header"}, status=400)
    token = auth.split(' ')[1]

    try:
        # 1) Fetch metadata
        meta_url = (
            f"https://graph.microsoft.com/v1.0/sites/{site_id}"
            f"/drives/{drive_id}/items/{file_id}"
            "?$select=name,webUrl"
        )
        headers = {'Authorization': f'Bearer {token}'}
        meta_resp = requests.get(meta_url, headers=headers)
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        filename = meta.get('name', '')
        resume_url = meta.get('webUrl', '')
        ext = filename.rsplit('.', 1)[-1].lower()

        # 2) Download content
        dl_url = (
            f"https://graph.microsoft.com/v1.0/sites/{site_id}"
            f"/drives/{drive_id}/items/{file_id}/content"
        )
        dl_resp = requests.get(dl_url, headers=headers)
        dl_resp.raise_for_status()
        content = dl_resp.content

        # 3) Extract text from resume
        if ext == 'pdf':
            resume_text = extract_text_from_pdf(content)
        elif ext in ('docx', 'doc'):
            resume_text = extract_text_from_docx(content)
        else:
            return Response({"error": f"Unsupported file type: .{ext}"}, status=400)

        # 4) Enhanced LLM Prompt for Parsing Resume
        prompt = f"""
You are a highly advanced resume parsing assistant. 
Parse the following resume text and generate a structured JSON object with the following fields:

1. "name": The full name of the candidate
2. "email": The email address of the candidate
3. "phone": The contact number of the candidate
4. "skills": A flat list of all technical and professional skills (e.g., ["Python", "AWS", "React"])
5. "projects": A list of projects with:
   - "name": The project name
   - "description": A brief description of the project
6. "education": A list of education details with:
   - "degree": Name of the degree
   - "institution": Educational institution
   - "duration": Duration of the course
7. "experience": A list of work experiences with:
   - "company": Company name
   - "role": Job role
   - "start_date": Start date
   - "end_date": End date
   - "description": Role description
8. "profile_summary": A brief professional summary if available
9. "domain_classification": A list of one or more roles such as:
   - "Frontend Developer", "Backend Developer", "Data Engineer", "Full Stack Developer", "DevOps Engineer", "ML Engineer", "Database Administrator"
10. "total_years_of_experience": A numeric value representing the total years of professional experience

Respond ONLY with a well-formatted JSON object.

Resume text:
\"\"\"
{resume_text}
\"\"\"
"""

        # 5) Send to LLM API
        llm_resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            headers={'Content-Type': 'application/json'}
        )
        llm_json = llm_resp.json()
        raw_text = llm_json['candidates'][0]['content']['parts'][0]['text'].strip()
        json_str = re.sub(r'^```json|```$', '', raw_text, flags=re.MULTILINE).strip()
        parsed = json.loads(json_str)

        # 6) Normalize skills and calculate experience
        parsed['skills'] = list(set(parsed.get('skills', [])))  # Remove duplicates

        # if 'total_years_of_experience' not in parsed or not parsed['total_years_of_experience']:
        #     parsed['total_years_of_experience'] = calculate_experience(parsed.get('experience', []))

        # 7) Prepare candidate data for database
        defaults = {
            'name': parsed.get('name', ''),
            'email': parsed.get('email', ''),
            'phone': parsed.get('phone', ''),
            'profile_summary': parsed.get('profile_summary', ''),
            'parsed_data': parsed,
            'resume_url': resume_url,
            'skills': parsed.get('skills', []),
            'domain_classification': parsed.get('domain_classification', []),
            'total_years_of_experience': parsed.get('total_years_of_experience', 0)
        }

        # 8) Get or create candidate record
        candidate, created = Candidate.objects.get_or_create(
            file_id=file_id,
            defaults={'resume_id': get_random_string(12), **defaults}
        )
        if not created:
            for field, val in defaults.items():
                setattr(candidate, field, val)
            candidate.save()

        # 9) Return complete response with additional fields
        return Response({
            "candidate": {
                "id": candidate.id,
                "resume_id": candidate.resume_id,
                "file_id": candidate.file_id,
                "name": candidate.name,
                "email": candidate.email,
                "phone": candidate.phone,
                "profile_summary": candidate.profile_summary,
                "skills": candidate.skills,
                "domain_classification": candidate.domain_classification,
                "total_years_of_experience": candidate.total_years_of_experience,
                "parsed_data": candidate.parsed_data,
                "resume_url": candidate.resume_url,
            }
        })

    except Exception as e:
        logger.exception("Unexpected error in parse_resume")
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
        data.append({
            "id":               c.id,
            "name":             c.name,
            "email":            c.email,
            "phone":            c.phone,
            "resume_url":       c.resume_url,
            "skills":           c.skills,   # Directly from the model
            "profile_summary":  c.profile_summary,  # Directly from the model
            "domain_classification": c.domain_classification,  # Directly from the model
            "total_years_of_experience": c.total_years_of_experience,  # Directly from the model
            "parsed_data":      c.parsed_data
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
