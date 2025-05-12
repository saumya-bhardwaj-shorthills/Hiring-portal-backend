from django.db import models

class ParsedResume(models.Model):
    filename = models.CharField(max_length=255)
    profile_summary = models.TextField()
    skills = models.TextField()
    projects = models.TextField()
    experience = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class SharePointSite(models.Model):
    site_url = models.URLField(unique=True)
    site_id = models.CharField(max_length=255)
    drive_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.site_url

class Candidate(models.Model):
    file_id = models.CharField(max_length=255, unique=True)
    resume_id = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    profile_summary = models.TextField(blank=True, null=True)
    resume_url = models.URLField(blank=True, null=True)
    parsed_data = models.JSONField(blank=True, null=True)    
    skills = models.JSONField(default=list, blank=True, null=True)                  # Stores the list of skills
    domain_classification = models.JSONField(default=list, blank=True, null=True)   # Stores the domain classifications
    total_years_of_experience = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)  # Stores the years of experience


    def __str__(self):
        return self.name