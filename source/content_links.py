"""Match explicitly provided URLs even when whitespace follows the scheme colon.
This never rewrites the displayed post and never relaxes the no-link variant.
"""
import re
from urllib.parse import urlsplit,urlunsplit
LINK=re.compile(r'(https?)\s*:\s*//\s*([^\s<>"“”]+)',re.I)

def supplied_urls(text):
    result=set()
    for match in LINK.finditer(text):
        value=match[1].lower()+'://'+match[2].rstrip('.,;!)]}')
        try:
            parsed=urlsplit(value)
            if not parsed.hostname or parsed.username or parsed.password:raise ValueError('URL không hợp lệ.')
            result.add(urlunsplit((parsed.scheme,parsed.netloc.lower(),parsed.path,parsed.query,parsed.fragment)))
        except ValueError:raise ValueError('URL không hợp lệ; không lưu bản nháp này.') from None
    return result

def validate_provided_urls(body,brief):
    if not supplied_urls(body).issubset(supplied_urls(brief)):
        raise ValueError('AI tạo URL chưa được cung cấp hoặc đã đổi mã link. Không lên lịch bài này.')
