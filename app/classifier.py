import re

CATEGORIES = ("status_question", "document_upload", "schedule_call", "other")

# Checked in order: the first category with a matching keyword wins.
KEYWORDS = (
    ("document_upload", ("document", "documents", "attached", "upload", "photo")),
    ("schedule_call", ("schedule", "call", "appointment", "reschedule")),
    ("status_question", ("status", "update", "hearing", "case")),
)


class KeywordClassifier:
    def classify(self, text: str) -> str:
        words = set(re.findall(r"[a-z]+", text.lower()))
        for category, keywords in KEYWORDS:
            if words.intersection(keywords):
                return category
        return "other"
