"""Shared writing voice and vocabulary checks; no model fine-tuning."""
import re

EXAMPLES = (
    'Anh em nào muốn lên rank an toàn, ghé Discord bên mình để trao đổi thêm nhé.',
    'Thua quá thì phải làm sao? Anh em ghé bên mình để được hỗ trợ nhé.',
    'Chơi game khó quá thì làm sao hả anh em?',
    'Ghé Discord để tìm hiểu các game và nhiều phiên bản, lựa chọn theo nhu cầu với giá cả hợp lý.',
)
GAME_EXAMPLES = {
    'valorant': ('Bắn Valorant mà gặp kèo căng thì anh em tính sao?',),
    'pubg': ('Bắn PUBG mãi vẫn gặp kèo khó? Anh em ghé bên mình trao đổi nhé.',),
    'cs2': ('Bắn CS2 gặp kèo căng thì làm sao hả anh em?',),
    'delta force': ('Cày đồ vật phẩm hiếm siêu dễ anh em ơi.',),
    'the isle': ('Khủng long to chưa chắc đã ăn được tớ.',
                 'Khủng long to chỉ là chuyện nhỏ.',),
    'lol': ('Đánh LOL gặp trận khó? Ghé bên mình để tìm hiểu hỗ trợ nhé.',),
}
GAME_LANGUAGE = {
    'valorant': 'Valorant: dùng bắn Valorant, bắn rank, chơi Valorant, vào trận; không dùng đánh Valorant, đánh rank hoặc đánh trận.',
    'pubg': 'PUBG: dùng bắn PUBG, chơi PUBG, vào trận; không dùng đánh PUBG hoặc đánh trận.',
    'cs2': 'CS2: dùng bắn CS2, chơi CS2, vào trận; không dùng đánh CS2 hoặc đánh rank.',
    'delta force': 'Delta Force: dùng bắn Delta Force, cày đồ, kiếm vật phẩm, chơi Delta Force. Không dùng đánh Delta Force. Chỉ nhắc vật phẩm hiếm khi brief cung cấp, không tự hứa kiếm đồ dễ hoặc chắc chắn.',
    'lol': 'LOL (Liên Minh Huyền Thoại): dùng đánh LOL, chơi LOL, đi đường, giao tranh. Không dùng bắn LOL hoặc lấy giọng game bắn súng cho toàn bài.',
    'the isle': 'The Isle là chủ đề khủng long và sinh tồn. Dùng chơi The Isle, sinh tồn, khủng long, chạm mặt khủng long lớn. Giọng vui, tự tin, trêu nhẹ như Khủng long to chưa chắc đã ăn được tớ hoặc Khủng long to chỉ là chuyện nhỏ. Đây là mẫu giọng văn để biến tấu, không phải lời bảo đảm thắng mọi khủng long; không chép cùng một câu mở đầu cho mọi bài. Không dùng bắn rank, súng đạn, leo rank hoặc cày vật phẩm hiếm của game khác.',
}
FPS_GAMES = {'valorant', 'pubg', 'cs2', 'delta force'}
_WRONG_FPS_VERB = re.compile(r'\bđánh\b(?!\s+(?:giá|dấu|đổi)\b)',re.I)
TERMS = ('cheat', 'cheats', 'cheating', 'hack', 'hacks', 'hacker', 'hackers', 'hacking',
         'aimbot', 'aim bot', 'wallhack', 'wall hack', 'esp', 'gian lận')
_PATTERN = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(x).replace(r'\ ', r'\s+') for x in TERMS) + r')(?!\w)', re.I)

GUIDANCE = (
    'Không tự thêm chỗ trống cho đường dẫn như [link Discord], [link], <link>, {link}, URL_HERE hoặc câu Ghé ngay: rồi để trống. '
    'Ứng dụng tự ghép nội dung liên hệ cố định sau khi AI viết; chỉ viết nội dung chính hoàn chỉnh, không nhắc người dùng chèn link, bỏ dấu cách hay xuống bình luận. '
    'Mục tiêu bài quảng cáo là giới thiệu dịch vụ tới khách hàng quan tâm, không phải tuyển bạn chơi hay tìm đồng đội. '
    'Không viết tìm bạn, tìm người chơi chung, kiếm đồng đội, tuyển team hoặc rủ lập đội. '
    'Giữ mục tiêu quảng cáo theo dữ kiện, nhưng tuân theo bố cục riêng trong writing_direction và length_target; không ép mọi bài thành hai đoạn hoặc cùng kiểu hỏi game khó rồi Ghé ngay. '
    'Không viết như khảo sát cộng đồng (hôm nay chơi thế nào, đi đường nào, chia sẻ pha hay), không hỏi lan man. '
    'Mỗi bài thay đổi góc mở và nhịp câu; giọng nói gần gũi anh em/bên mình, tránh văn mẫu trang trọng hoặc thông báo. '
    'Các từ tà đạo, khóa chỉ là ví dụ giọng nói, không tự suy ra hay che giấu tính năng sản phẩm; không tự thêm chúng vào bài. '
    'Giọng riêng: thân thiện như đang nói với anh em chơi game, ngắn gọn, tự nhiên; '
    'có thể mở bằng một câu hỏi, nhu cầu, lời tâm sự hoặc lời mời; vui, trêu nhẹ chuyện chơi game khó, không công kích. '
    'Ví dụ chỉ minh họa giọng văn, KHÔNG là dữ kiện sản phẩm và KHÔNG chép nguyên mẫu. '
    'Chỉ nhắc Discord, nhiều game/phiên bản, hỗ trợ hoặc giá hợp lý khi brief thực sự cung cấp. '
    'Không nhắc cheat, hack, aimbot, ESP, wallhack, gian lận trong title/body/body_no_link, kể cả lời phủ định. '
    'Không suy diễn từ ảnh thành công dụng sản phẩm; không tự thêm khóa, gói hàng, lời hứa game dễ hoặc kéo rank. Nếu dữ kiện không đủ để viết trung thực thì yêu cầu bổ sung. '
    'Không biến mong muốn lên rank an toàn thành lời bảo đảm không bị khóa tài khoản hay chắc thắng. '
    'Ví dụ theo game chỉ dùng cho đúng game; không mang khủng long sang game bắn súng hoặc dùng cày vật phẩm hiếm cho mọi game. '
    'Ví dụ không chứng minh kết quả: không tự hứa rơi đồ hiếm, bất bại hoặc chắc thắng. '
    'Các bài phải khác cách mở, nhịp câu, thứ tự ý và lời mời; không chỉ đổi tên game hoặc vài từ đồng nghĩa. '
    'Ưu tiên chọn một góc dẫn khác hẳn các bài gần đây: nhu cầu, lựa chọn, thông tin trực tiếp, câu trêu nhẹ hoặc lời mời. Không tự bịa tình huống cá nhân, câu chuyện khách hàng hay tính năng để tạo khác biệt. '
    'Thông tin dịch vụ, game, nơi liên hệ và dữ kiện được giữ nguyên ý nghĩa; diễn đạt lại linh hoạt. Phần liên hệ cố định do ứng dụng nối sau, không viết lại phần đó. '
    'Đừng lặp cả hai câu Ghé ngay hoặc Anh em nào trong mọi bài. Không hạ thấp người đọc vì thua trận.'
    ' Không giữ nguyên cả câu mô tả dịch vụ hay lời mời của bài trước rồi chỉ đổi câu mở đầu. Diễn đạt lại cả phần thân bài, vẫn giữ nguyên ý và dữ kiện.'
)

def apply(system, context):
    context['voice_examples'] = list(EXAMPLES)
    category = str(context.get('category') or context.get('group', {}).get('category', '')).strip().casefold()
    context['game_voice_examples'] = list(GAME_EXAMPLES.get(category, ()))
    context['game_language'] = GAME_LANGUAGE.get(category,'Dùng từ tự nhiên đúng game trong category; không mượn thuật ngữ game khác.')
    return system + ' ' + GUIDANCE + ' Quy tắc từ ngữ bắt buộc theo game: ' + context['game_language']

def issue(title, body, alt, footer='', category=''):
    if any(re.search(r'(?:\[|\{|<)\s*(?:link|url|đường\s+dẫn)(?:\s+[^\]\}>\n]{0,60})?\s*(?:\]|\}|>)|\b(?:URL_HERE|LINK_HERE)\b',str(v),re.I) for v in (title,body,alt)):
        return 'Không để placeholder như [link Discord]. Bỏ cả dòng lời mời trống chỉ dẫn chèn link; viết nội dung chính hoàn chỉnh. Ứng dụng tự nối phần liên hệ cố định, AI không viết lại phần đó.'
    if any(_PATTERN.search(str(value)) for value in (title, body, alt, footer)):
        return 'Có từ thuộc danh sách cần tránh. Viết lại cả tiêu đề và hai phiên bản bằng tiếng Việt tự nhiên, không nhắc từ đó dù dưới dạng phủ định; không che giấu hoặc bịa công dụng, không thêm cam kết an toàn.'
    if any(re.search(r'\b(?:tìm bạn|tìm người chơi chung|kiếm đồng đội|tuyển team|rủ lập đội)\b',str(v),re.I) for v in (title,body,alt)):
        return 'Sai mục tiêu: viết lời giới thiệu dịch vụ cho khách hàng quan tâm theo brief, không tuyển bạn chơi hoặc đồng đội. Mở ngắn đúng game, kết bằng lời mời trao đổi tại Discord khi brief cung cấp.'
    if str(category).strip().casefold() in FPS_GAMES and any(_WRONG_FPS_VERB.search(str(v)) for v in (title,body,alt)):
        return 'Sai cách gọi hành động của game bắn súng: dùng bắn hoặc chơi, không dùng đánh trận/đánh rank/đánh game. Với Delta Force có thể dùng cày đồ, kiếm vật phẩm theo dữ kiện. Viết lại tiêu đề và hai phiên bản tự nhiên đúng game, giữ nguyên dữ kiện.'
    return ''
