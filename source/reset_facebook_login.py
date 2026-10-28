"""Interactive Facebook-only cookie reset for the bot's private Edge profile.

Creating/importing this module never changes browser data. Actual deletion needs
closed bot/browser processes and an explicit typed confirmation.
"""
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import sys

FACEBOOK_ROWS = "lower(host_key) IN ('facebook.com','.facebook.com') OR lower(host_key) LIKE '%.facebook.com'"


def cookie_files(profile):
    profile=Path(profile).resolve()
    candidates=[]
    for folder in [profile/'Default',*profile.glob('Profile *')]:
        for relative in ('Network/Cookies','Cookies'):
            candidate=folder/relative
            if not candidate.is_file():continue
            resolved=candidate.resolve()
            if not resolved.is_relative_to(profile):
                raise RuntimeError('Tệp cookie nằm ngoài profile riêng của bot; đã dừng.')
            if resolved not in candidates:candidates.append(resolved)
    return candidates


def clear_facebook_cookies(profile):
    total=0
    for file in cookie_files(profile):
        # mode=rw never creates or replaces a database. No cookie values are read.
        with closing(sqlite3.connect(file.as_uri()+'?mode=rw',uri=True,timeout=2)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            if not any(row[1]=='host_key' for row in connection.execute('PRAGMA table_info(cookies)')):
                raise RuntimeError('Không nhận diện được cơ sở dữ liệu cookie Edge; đã dừng.')
            total+=connection.execute('DELETE FROM cookies WHERE '+FACEBOOK_ROWS).rowcount
    return total


def blocking_processes(root,data):
    import psutil
    from desktop import profile_matches
    blocked=[]
    for process in psutil.process_iter(['pid','name','cmdline','cwd']):
        if process.pid==os.getpid():continue
        info=process.info;name=(info['name'] or '').lower();args=info['cmdline'] or []
        if name=='msedge.exe':
            if not args or profile_matches(args,data):blocked.append('Edge riêng của bot')
        elif name in {'python.exe','pythonw.exe','py.exe'}:
            scripts=[Path(arg) for arg in args if Path(arg).name in {'app.py','desktop.py'}]
            if scripts and ((info['cwd'] and Path(info['cwd']).resolve()==root) or any(p.is_absolute() and p.parent.resolve()==root for p in scripts)):
                blocked.append('NCT Group Manager / worker đăng bài')
    return sorted(set(blocked))


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    root=Path(__file__).resolve().parent
    data=Path(os.environ.get('NCT_DATA_DIR',str(root/'data'))).resolve()
    from desktop import browser_kind
    if browser_kind(data)=='chrome':
        print('Tool đang dùng Chrome. File này chỉ dành cho hồ sơ Edge riêng cũ; chưa xóa cookie nào.')
        print('Nếu cần đăng nhập lại, hãy tự đăng xuất Facebook trong đúng cửa sổ Chrome của tool.')
        return 2
    profile=data/'edge-profile'
    print('NCT — Đăng nhập lại Facebook cho bot\n')
    print('Chỉ xóa cookie facebook.com trong profile Edge riêng của bot.')
    print('Giữ nguyên kho ảnh/video, bài viết, lịch, cấu hình, key và dữ liệu đăng nhập đã lưu của các website khác.')
    print('Cookie bị xóa sẽ khiến Facebook trong profile này đăng xuất. Bạn tự đăng nhập lại trên Edge.\n')
    try:
        blocked=blocking_processes(root,data)
        if blocked:
            print('Chưa thực hiện: hãy Tạm dừng và thoát tool, sau đó đóng cửa sổ Edge riêng của bot.')
            print('Đang mở: '+', '.join(blocked))
            input('\nNhấn Enter để đóng. Sau khi đóng các ứng dụng trên, chạy lại file này. ')
            return 2
        if input('Gõ XOA rồi Enter để xác nhận, hoặc Enter để hủy: ').strip()!='XOA':
            print('Đã hủy, cookie được giữ nguyên.');return 0
        # Recheck after confirmation so opening the tool during the prompt is safe.
        if blocking_processes(root,data):raise RuntimeError('Tool hoặc Edge vừa mở lại. Hãy đóng rồi chạy lại file.')
        count=clear_facebook_cookies(profile)
        print(f'Đã xóa {count} cookie Facebook. Không đọc hoặc hiển thị giá trị cookie.')
        from desktop import launch_browser
        launch_browser(data,'https://www.facebook.com/')
        print('Đã mở Facebook trong đúng Edge riêng. Hãy tự đăng nhập, rồi mở lại tool khi xong.')
        input('\nNhấn Enter để đóng cửa sổ hướng dẫn này. ')
        return 0
    except (OSError,sqlite3.Error,RuntimeError) as error:
        print('Chưa hoàn tất: '+str(error))
        print('Không xóa toàn bộ profile. Giữ tool và Edge đóng rồi thử lại.')
        input('\nNhấn Enter để đóng. ')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
