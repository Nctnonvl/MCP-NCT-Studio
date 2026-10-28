"""One short final Telegram card after post and optional comment finish."""
import datetime as dt

def render(job, result):
    state=result.get('state','uncertain')
    label={'submitted':'✅ Đã đăng','pending':'⏳ Chờ duyệt','prepared':'📝 Đã điền, chưa đăng','error':'❌ Chưa đăng','uncertain':'⚠️ Cần kiểm tra'}.get(state,state)
    if result.get('moderation_status')=='removed':label='🚨 Bài đã bị gỡ'
    elif result.get('moderation_status')=='declined':label='⛔ Bài bị từ chối'
    lines=[f"{label} · lượt #{job['id']} · bài #{job.get('content_id',0)}",job['group_name'][:110]]
    mode=result.get('posting_identity_effective',result.get('posting_identity','default'))
    if 'post_identity_verified' in result:
        actual=result.get('post_identity');actor=result.get('post_actor','')
        if not result['post_identity_verified']:lines.append('Danh tính bài: chưa xác minh.')
        elif actual=='anonymous':lines.append('Danh tính bài: ẩn danh.')
        elif actual=='nickname':lines.append('Danh tính bài: biệt danh '+actor[:70]+'.')
        else:lines.append('Danh tính hiển thị: '+actor[:70]+' (không gắn nhãn ẩn danh).')
    elif result.get('identity_verified') and mode in {'anonymous','nickname'}:
        lines.append('Danh tính: '+('ẩn danh.' if mode=='anonymous' else 'biệt danh đã chọn.'))
    elif result.get('identity_verified') and mode=='default':
        lines.append('Danh tính: hồ sơ chính.')
    if result.get('profile_fallback_used'):lines.append('Ẩn danh không khả dụng; đã chuyển sang hồ sơ chính trước khi gửi.')
    if result.get('post_url'):
        lines.append(result['post_url'])
    else:
        lines.append('Nhóm: '+job['url'])
    if result.get('verification_source')=='your_content':lines.append('Đối chiếu: Nội dung của bạn.')
    elif result.get('verification_source')=='post_permalink':lines.append('Đối chiếu: đúng nội dung và link bài.')
    elif 'your_content_checked' in result:lines.append('Nội dung của bạn: chưa đối chiếu được đúng bài.')
    status=result.get('comment_status','')
    if result.get('approval_rechecked'):lines.append('Đã kiểm tra lại trạng thái duyệt; không đăng bài mới.')
    if result.get('approval_tracking'):lines.append('Sẽ đối chiếu lại đúng bài mỗi 15–30 phút khi bật theo dõi duyệt.')
    if result.get('approval_requires_link'):lines.append('Chưa có link bài; gắn link trong Lịch đăng để theo dõi duyệt.')
    if job.get('comment_text'):
        lines.append({'waiting_approval':'Bình luận: đợi bài được duyệt.','sent':'Bình luận: đã gửi.','submitted':'Bình luận: đã gửi.','fallback_sent':'Bình luận: đã gửi nội dung TikTok.','failed':'Bình luận: gửi không thành công.','uncertain':'Bình luận: chưa xác nhận, không tự gửi lại.','skipped':'Bình luận: chưa gửi theo quy định nhóm.'}.get(status,'Bình luận: chưa xác nhận gửi.'))
        if status in {'sent','submitted','fallback_sent'} and result.get('comment_identity_effective'):
            lines[-1]+=' · '+result['comment_identity_effective'][:80]
        if status in {'failed','uncertain'}:lines.append(' '.join(result.get('comment_detail','').split())[:180])
        if result.get('comment_retry_exhausted'):
            lines[-2]='Bình luận: chưa được gửi sau 3 lần thử.'
    note=job.get('variant_note','')
    if note:
        lines.append(note[:140])
    if state not in {'submitted','prepared'}:
        detail=' '.join(result.get('detail','').split())
        lines.append(detail[:230])
        if state in {'pending','uncertain'}:
            lines.append('Không tự gửi lại bài này.')
    if result.get('queue_paused_for_review'):lines.append('Đã dừng lịch; cần xử lý cảnh báo hoặc yêu cầu dừng trước khi chạy lại.')
    elif result.get('queue_cooldown_until'):
        when=dt.datetime.fromtimestamp(result['queue_cooldown_until'],dt.timezone(dt.timedelta(hours=7))).strftime('%H:%M %d/%m')
        lines.append(f'Đủ 3 lỗi liên tiếp: nghỉ đến {when}, sau đó tiếp tục lịch; không tự gửi lại bài lỗi.')
    if result.get('queue_continues') and not result.get('queue_cooldown_until'):
        if result.get('queue_next_due'):
            when=dt.datetime.fromtimestamp(result['queue_next_due'],dt.timezone(dt.timedelta(hours=7))).strftime('%H:%M %d/%m')
            lines.append(f"Giữ lượt này kiểm tra. Lượt tiếp theo #{result.get('queue_next_id','')}: {when}.")
        else:lines.append('Giữ lượt này kiểm tra; tiếp tục các nhóm còn lại.')
    return '\n'.join(lines)[:900]
