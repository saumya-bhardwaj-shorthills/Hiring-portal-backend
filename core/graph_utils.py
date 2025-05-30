# core/graph_utils.py
import requests
from django.conf import settings

def get_access_token():
    url = f"https://login.microsoftonline.com/{settings.TENANT_ID}/oauth2/v2.0/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'client_id': settings.CLIENT_ID,
        'client_secret': settings.CLIENT_SECRET,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials',
    }
    response = requests.post(url, headers=headers, data=data)
    return response.json().get("access_token")

def fetch_sharepoint_files(access_token):
    headers = {'Authorization': f'Bearer {access_token}'}
    print("Resume fetched")
    url = f"{settings.GRAPH_API_ENDPOINT}/sites/{settings.SHAREPOINT_SITE_ID}/drives/{settings.SHAREPOINT_DRIVE_ID}/root/children"
    response = requests.get(url, headers=headers)
    return response.json().get('value', [])

def download_file(access_token, file_id):
    headers = {'Authorization': f'Bearer {access_token}'}
    download_url = f"{settings.GRAPH_API_ENDPOINT}/drives/{settings.SHAREPOINT_DRIVE_ID}/items/{file_id}/content"
    response = requests.get(download_url, headers=headers)
    return response.content

def get_site_id(access_token, domain, site_name):
    headers = {'Authorization': f'Bearer {access_token}'}
    url = f'https://graph.microsoft.com/v1.0/sites/{domain}:/sites/{site_name}'
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()['id']

def get_drive_id(access_token, site_id, drive_name):
    headers = {'Authorization': f'Bearer {access_token}'}
    url = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives'
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    drives = response.json().get('value', [])
    for drive in drives:
        if drive.get('name') == drive_name:
            return drive.get('id')
    raise ValueError(f'Drive named "{drive_name}" not found.')
