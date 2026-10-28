## Phát hành bản cập nhật

Đối với người phát hành: giữ khóa ký riêng ngoài Git. Khóa này **không có trong repository**. Không tạo khóa mới khi cập nhật cho những bản chính thức đã dùng khóa cũ. Nếu làm một fork độc lập, tạo khóa riêng bằng `python sign_update.py --init`, đổi khóa công khai và nguồn cập nhật cho fork trước khi build.

Sau khi build, tạo manifest bằng khóa riêng của người phát hành:

```powershell
python sign_update.py --version 1.2.0 --url https://github.com/OWNER/REPO/releases/download/v1.2.0/NCT-Studio-Setup.exe --installer output/NCT-Studio-Setup.exe
```

Phiên bản trong `source/online_update.py`, cấu hình native/Setup và manifest cần được cập nhật nhất quán. Đưa bộ cài và `output/update.json` lên cùng GitHub Release. Không đưa thư mục `signing` lên GitHub.

