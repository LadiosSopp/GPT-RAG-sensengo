import re

APPLICATION_INSIGHTS_CONNECTION_STRING = "APPLICATIONINSIGHTS_CONNECTION_STRING"
APP_NAME = "gpt-rag-ui"

# Constants
UUID_REGEX = re.compile(
    r'^\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s+',
    re.IGNORECASE
)

SUPPORTED_EXTENSIONS = [
    "pdf", "bmp", "jpeg", "jpg", "png", "tiff", "xlsx", "docx", "pptx",
    "md", "txt", "html", "shtml", "htm", "py", "csv", "xml", "json", "vtt"
]

# Regex to match Markdown links with file extensions
# Matches [title](url.ext) where:
# - title: any text not containing ]
# - url: path ending with supported extension, not containing )[, )、, or )  followed by [
# This prevents matching across multiple adjacent Markdown links
REFERENCE_REGEX = re.compile(
    r'\[([^\]]+)\]\(((?:(?!\)\s*[\[、\u3001]).)+\.(?:' + '|'.join(SUPPORTED_EXTENSIONS) + r'))\)',
    re.IGNORECASE
)

TERMINATE_TOKEN = "TERMINATE"