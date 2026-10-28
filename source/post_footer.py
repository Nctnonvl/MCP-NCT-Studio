"""Editable local footer appended by code, never rewritten by the language model."""
from content_links import supplied_urls,LINK
from store import has_link

def config(store):
    raw=store.get('post_footer',{})
    return {'enabled':raw.get('enabled') is True,'text':str(raw.get('text',''))}

def save(store,obj):
    text=str(obj.get('text','')).replace('\r\n','\n').strip();enabled=obj.get('enabled') is True
    if len(text)>1000 or (enabled and not text):raise ValueError('Nội dung cuối bài tối đa 1000 ký tự; nhập nội dung khi bật.')
    supplied_urls(text)
    store.set('post_footer',{'enabled':enabled,'text':text})
    return config(store)

def effective(cfg):return cfg['text'] if cfg['enabled'] else ''

def remove(text,footer):
    if not footer:return text.strip()
    # Remove reserved footer URLs from source text/history so the model cannot duplicate them in prose.
    reserved=supplied_urls(footer)
    text=text.replace(footer,'')
    def rewrite(match):return '' if supplied_urls(match.group(0)) & reserved else match.group(0)
    return LINK.sub(rewrite,text).strip()

def append(body,alt,cfg):
    footer=effective(cfg)
    if not footer:return body,alt,''
    base=remove(body,footer)
    if not base:raise ValueError('Bài thiếu nội dung chính ngoài phần cuối cố định.')
    result=base+'\n\n'+footer
    no_link=alt
    if not has_link(footer):no_link=remove(alt,footer)+'\n\n'+footer
    if len(result)>5000 or len(no_link)>5000:raise ValueError('Bài cộng nội dung cuối vượt 5000 ký tự; rút ngắn nội dung cố định.')
    return result,no_link,footer
