from core.llm_service import query_gemini

class ResumeProcessor:
    def __init__(self):
        self.fields = {
            "profile_summary": "Extract the profile summary if available, if not available write person's profile summary based on his experience and education.",
            "skills": "List the Person's technical and soft skills and classify them in groups",
            "projects": "List all the projects with it's name and brief summary of the project with technical stack used in the project.",
            "experience": "List down all the relevant work experience person has in chronological order"
        }

    def process(self, resume_text):
        results = {}
        for key, instruction in self.fields.items():
            prompt = f"{instruction}\n\nText:\n{resume_text}\n\nReturn as JSON."
            try:
                response = query_gemini(prompt)
                results[key] = response
            except Exception as e:
                results[key] = f"Error: {str(e)}"
        return results
    
    