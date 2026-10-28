"""An author's preview of a pending post is not proof of approval."""
from receipts import post_url

async def verify_pending(tool,observe,current_url,navigate_group,root,job,report):
    from own_content import verify
    from post_link_check import verify as verify_link
    link=post_url(job.get('post_url',''),job['url'])
    report('Đối chiếu đúng bài trong Nội dung của bạn trước khi xác nhận trạng thái duyệt')
    status=await verify(tool,observe,current_url,navigate_group,root,job,{'state':'pending','post_url':link},report)
    observed=post_url(status.get('post_url',''),job['url'])
    if status.get('state')=='submitted' and observed and (not link or observed==link):
        result=await verify_link(tool,observe,current_url,root,job,observed,report)
        if result.get('state')=='submitted':result.update(moderation_checked=True,moderation_status='submitted')
        return result
    if status.get('state')=='pending':
        return {**status,'state':'pending','post_url':observed or link,'comment_status':'waiting_approval','detail':'Đã đối chiếu đúng bài trong Đang chờ duyệt; chưa bình luận.'}
    if status.get('state')=='error':
        return {**status,'post_url':observed or link,'comment_status':'skipped'}
    return {**status,'state':'uncertain','post_url':link,'comment_status':'waiting_approval','detail':'Chưa có bằng chứng đúng bài đã được duyệt; không bình luận. '+status.get('your_content_detail','')[:250]}
