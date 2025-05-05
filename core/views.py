import logging
import requests
import fitz  # PyMuPDF
from io import BytesIO
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.conf import settings
from .graph_utils import download_file
import re
from .models import Candidate
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
    file_id = request.data.get('file_id')
    site_id = request.data.get('site_id')
    drive_id = request.data.get('drive_id')
    if not file_id or not site_id or not drive_id:
        return Response({"error": "File ID, Site ID, and Drive ID are required"}, status=400)

    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return Response({"error": "No authorization header"}, status=400)
        access_token = auth_header.split(' ')[1]

        # Step 1: Download resume file
        url = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/items/{file_id}/content'
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        file_content = response.content

        # Step 2: Extract text from PDF
        resume_text = extract_text_from_pdf(BytesIO(file_content))
        logger.debug(f"[RESUME TEXT]: {resume_text[:300]}...")

        # Step 3: Construct Gemini prompt
        prompt = f"""
Given the following resume text, return a JSON object with these fields:

1. name (string)
2. skills (grouped under categories like Programming Languages, Frameworks, Tools, etc.)
3. projects (list of projects with name and description)
4. education (list with degree, institution, duration)
5. experience (chronologically sorted with role, company, duration, and description)
6. profile_summary (use existing summary if present, else write a brief one)

Respond only with a valid JSON object. No extra commentary.

Resume text:
\"\"\"
{resume_text}
\"\"\"
"""

        # Step 4: Call Gemini
        llm_response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            headers={'Content-Type': 'application/json'}
        )

        llm_json = llm_response.json()
        logger.debug(f"[LLM RAW RESPONSE]: {llm_json}")

        # Step 5: Extract and return raw string response from Gemini
        response_text = llm_json['candidates'][0]['content']['parts'][0]['text'].strip()
        json_str = re.sub(r'^```json|```$', '', response_text.strip(), flags=re.MULTILINE).strip()

        parsed_json = json.loads(json_str)

        # Create a Candidate record
        candidate = Candidate.objects.create(
            resume_id=get_random_string(12),
            name=parsed_json.get("name", "Unknown"),
            email=parsed_json.get("email", ""),
            phone=parsed_json.get("phone", ""),
            profile_summary=parsed_json.get("profile_summary", ""),
            parsed_data=parsed_json
        )

        return Response({"parsed": json.dumps(parsed_json, indent=2)})
    except Exception as e:
        logger.exception("Unexpected error while parsing resume")
        return Response({"error": str(e)}, status=500)


@api_view(['GET'])
def search_candidates(request):
    keyword = request.GET.get("keyword", "").lower()
    if not keyword:
        return Response({"error": "Keyword is required"}, status=400)

    matching_candidates = Candidate.objects.filter(
        Q(parsed_data__icontains=keyword)
    )

    results = [
        {
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,
            "summary": candidate.profile_summary,
            "parsed_data": candidate.parsed_data,
        }
        for candidate in matching_candidates
    ]
    return Response({"results": results})

        
