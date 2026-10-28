import json
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, payload=None, timeout=30, headers=None, local_only=False):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'NCT-Group-Manager/1.0', **(headers or {})})
    try:
        open_url=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open if local_only else urllib.request.urlopen
        with open_url(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            body=json.loads(exc.read());detail=body.get('error') or body.get('detail') or body.get('description') or ''
            if isinstance(detail,dict):detail=detail.get('message') or detail.get('code') or ''
            error=f'HTTP {exc.code}: {str(detail)[:400]}'
        except (ValueError, OSError):
            error = f'HTTP {exc.code}'
        raise RuntimeError(str(error)[:400]) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError('Không kết nối được dịch vụ hoặc hết thời gian chờ.') from None

