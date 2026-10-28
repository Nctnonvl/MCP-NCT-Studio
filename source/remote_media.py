"""Bounded public image URL intake for the clipboard attachment control."""
import io
import ipaddress
import socket
import urllib.request
from urllib.parse import urlsplit

import media


def check_url(url):
    parsed=urlsplit(url)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Dùng link ảnh trực tiếp HTTP hoặc HTTPS.')
    try:
        addresses=socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)
    except (OSError,ValueError) as exc:
        raise ValueError('Không kết nối được máy chủ ảnh.') from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Chỉ nhận link ảnh công khai trên Internet.')
    return url


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        check_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def receive_image(url,directory):
    if not isinstance(url,str) or len(url)>8192:
        raise ValueError('Link ảnh không hợp lệ.')
    check_url(url)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),PublicRedirect())
    try:
        with opener.open(urllib.request.Request(url,headers={'User-Agent':'NCT-Studio/1.0'}),timeout=30) as response:
            mime=response.headers.get_content_type()
            extension={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}.get(mime)
            if not extension:
                raise ValueError('Link phải mở trực tiếp ảnh JPG, PNG hoặc WEBP; không phải trang xem ảnh.')
            length=response.headers.get('Content-Length')
            if length and int(length)>media.MAX_IMAGE_UPLOAD:
                raise ValueError('Ảnh tối đa 100 MB.')
            raw=response.read(media.MAX_IMAGE_UPLOAD+1)
            if len(raw)>media.MAX_IMAGE_UPLOAD:
                raise ValueError('Ảnh tối đa 100 MB.')
        return media.receive(io.BytesIO(raw),len(raw),'anh-da-dan'+extension,directory)
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError('Không tải được ảnh từ link này. Hãy sao chép ảnh rồi Ctrl+V hoặc tải tệp lên.') from exc
