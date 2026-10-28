"""Detect copied drafts without using external semantic services."""
import re
from difflib import SequenceMatcher
DIRECTIONS=(
 'Mở bằng nhu cầu cụ thể đã có trong dữ kiện; trình bày lời mời ở cuối, đổi câu mở đầu so với bài gần đây.',
 'Giới thiệu nơi trao đổi trước, sau đó nêu thông tin người đọc có thể tìm thấy. Viết trực tiếp, không câu hỏi.',
 'Mở bằng một câu hỏi thực tế dựa trên dữ kiện, sau đó trả lời bằng thông tin được cung cấp.',
 'Thông tin chính trước rồi cách liên hệ, không kể lể về trận thua. Đổi câu mở đầu hoàn toàn.',
 'Mở bằng lời tâm sự về nhu cầu đã nêu, rồi mời trao đổi; không bịa trải nghiệm cá nhân.',
 'Đặt thông tin lựa chọn lên trước, lời hỗ trợ ở cuối nếu brief có; tránh lặp Ghé ngay.',
 'Hỏi anh em một câu ngắn đúng nhu cầu trong brief, dùng lời mời nhẹ nhàng.',
 'Mở trực tiếp bằng thông tin có thật, không dùng câu hỏi; thay đổi nhịp ngắn dài giữa các câu.',
 'Mở bằng một câu hỏi vui về game khó hoặc trận thua nếu dữ kiện có, rồi chuyển nhẹ sang lời mời; không hứa chắc thắng.',
 'Trêu nhẹ một tình huống chơi game đã được cung cấp; giữ một câu dẫn ngắn và lời mời khác các bài cũ.',
 'Tập trung một ý chính trong dữ kiện, diễn đạt ngắn gọn 2–3 câu. Không dùng lời kêu gọi sáo rỗng.',
 'Đưa nhu cầu lựa chọn nhiều phiên bản lên đầu nếu brief có; không mở bằng thua trận hoặc game khó.',
 'Lời mời trao đổi ở câu đầu, thông tin dịch vụ ở sau; không dùng Ghé ngay hay Anh em nào.',
 'Một câu cảm thán trêu nhẹ đúng game, rồi chuyển trực tiếp sang dữ kiện; không đặt câu hỏi.',
 'Nói thẳng thông tin có thật theo giọng trò chuyện; không mở bằng câu hỏi tu từ hoặc kể chuyện thua.',
 'Tập trung việc tìm hiểu lựa chọn phù hợp nhu cầu nếu có trong brief, kết bằng lời mời ngắn không giống bài cũ.')

FORMATS=(
 'Một đoạn liền 3 câu, câu đầu ngắn và câu sau dài hơn; không dùng bố cục hai đoạn quen thuộc.',
 'Hai đoạn không cân nhau: một câu mở rất ngắn, đoạn sau trình bày dữ kiện và lời mời.',
 'Ba dòng ngắn, mỗi dòng một vai trò: dẫn chuyện, dữ kiện, lời mời. Không đặt tiêu đề cho các dòng.',
 'Hai câu liền mạch: một câu dẫn nối dữ kiện, một câu mời. Không lặp lại toàn bộ dữ kiện ở cả hai câu.',
 'Đưa thông tin chính trước; câu chốt ngắn, thân thiện. Không dựng câu hỏi rồi tự trả lời.')

def blueprint(serial):
    direction=DIRECTIONS[serial%len(DIRECTIONS)]
    layout=FORMATS[(serial*3+serial//len(DIRECTIONS))%len(FORMATS)]
    length=('25–40','40–60','55–80')[(serial+serial//len(DIRECTIONS))%3]
    return {'writing_direction':direction+' '+layout,'length_target':length+' từ cho nội dung chính; không kéo dài bằng ý ngoài brief.'}

def normalized(text):
    text=re.sub(r'https?\s*:\s*//\S+',' ',str(text).casefold())
    text=re.sub(r'\b(?:valorant|delta\s+force|pubg|cs\s*2|cs\s*:?\s*go|the\s+isle|lol|liên minh huyền thoại)\b',' game ',text)
    return ' '.join(re.findall(r'\w+',text))
def similarity(a,b):return SequenceMatcher(None,normalized(a),normalized(b)).ratio()

def shared_sentence(body,references):
    sentences=[s.strip() for s in re.split(r'[.!?\n]+',body) if len(normalized(s))>=50 and len(normalized(s).split())>=10]
    for ref in references:
        for old in re.split(r'[.!?\n]+',ref):
            if len(normalized(old))<50 or len(normalized(old).split())<10:continue
            for sentence in sentences:
                if similarity(sentence,old)>=.86:return sentence
    return ''
def copied(body,references):
    if shared_sentence(body,references):return True
    opening=re.split(r'[.!?](?:\s|$)',body,maxsplit=1)[0]
    for ref in references:
        if not ref.strip():continue
        # Long marketing drafts should differ beyond replacing game names or
        # synonyms. Short factual phrases alone are not enough to reject a post.
        if similarity(body,ref)>(.72 if min(len(normalized(body)),len(normalized(ref)))>=90 else .9):return True
        first=re.split(r'[.!?](?:\s|$)',ref,maxsplit=1)[0]
        if min(len(normalized(first)),len(normalized(opening)))>=28 and similarity(opening,first)>.86:return True
        left=normalized(body).split();right=normalized(ref).split()
        if min(len(left),len(right))>=14:
            a={tuple(left[i:i+3]) for i in range(len(left)-2)}
            b={tuple(right[i:i+3]) for i in range(len(right)-2)}
            if a and b and 2*len(a&b)/(len(a)+len(b))>=.55:return True
    return False
