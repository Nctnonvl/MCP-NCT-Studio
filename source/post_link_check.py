"""Verify a known post permalink before any comment; never create a post."""
import asyncio
from receipts import post_url,has_verified_post
from post_context import own_post_context,clean
from post_comments import open_observed_post,finish_post
from facebook_labels import APPROVAL

PENDING=('bài viết đang chờ duyệt','bài viết của bạn đang chờ','bài viết này đang chờ','đang chờ quản trị viên phê duyệt','pending approval','post is pending','publication est en attente')

async def verify(tool,observe,current_url,root,job,link,report):
    link=post_url(link,job['url'])
    if not link:return {'state':'uncertain','comment_status':'skipped','detail':'Chưa lấy được link đúng bài; không bình luận hoặc đăng lại.'}
    if post_url(await current_url(),job['url'])!=link:
        if not await open_observed_post(tool,observe,{'url':link},job['url']):
            return {'state':'uncertain','comment_status':'skipped','detail':'Không mở được link bài đã xác minh; không bình luận.'}
    report('Tải lại link bài; xác minh trạng thái xuất bản trước khi bình luận')
    await tool('Shortcut',{'shortcut':'ctrl+r'});await asyncio.sleep(2)
    await observe(True)
    if post_url(await current_url(),job['url'])!=link:
        return {'state':'uncertain','post_url':link,'comment_status':'skipped','detail':'Link bài không còn mở đúng bài đích; cần kiểm tra, không bình luận.'}
    context=await asyncio.to_thread(own_post_context,root,job['body'])
    if not context or context.get('caption_seen') is not True:
        return {'state':'uncertain','post_url':link,'comment_status':'skipped','detail':'Chưa đối chiếu đủ nội dung tại link bài; chưa thể kết luận đã duyệt.'}
    text=clean(' '.join(context.get('outside_texts',[])))
    if any(marker in text for marker in PENDING+APPROVAL):
        return {'state':'pending','post_url':link,'comment_status':'waiting_approval','detail':'Bài vẫn đang chờ duyệt; chưa bình luận.'}
    result=await finish_post(tool,observe,current_url,root,job,{},True)
    if has_verified_post(result,job['url']):
        result['detail']='Đã xác nhận đúng nội dung và bài đã xuất bản qua link.'
        return result
    return {'state':'uncertain','post_url':link,'comment_status':'skipped','detail':'Chưa xác minh được bài đã xuất bản qua link; không bình luận.'}
