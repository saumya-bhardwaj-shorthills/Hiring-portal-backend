from django.db import models

class ParsedResume(models.Model):
    filename = models.CharField(max_length=255)
    profile_summary = models.TextField()
    skills = models.TextField()
    projects = models.TextField()
    experience = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class Candidate(models.Model):
    resume_id = models.CharField(max_length=200, unique=True)
    name = models.CharField(max_length=255)
    email = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    profile_summary = models.TextField()
    parsed_data = models.JSONField()

    def __str__(self):
        return self.name
    


