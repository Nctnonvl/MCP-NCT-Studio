# NCT Studio

Ứng dụng Windows để quản lý nội dung, nhóm Facebook và lịch đăng theo từng tài khoản.

## Tải và cài

Mở [Releases](https://github.com/Nctnonvl/MCP-NCT-Studio/releases), tải `NCT-Studio-Setup.exe` hoặc bản Portable. Bản desktop mang theo Python và Windows MCP; giao diện mở trong cửa sổ ứng dụng.

Hỗ trợ Windows 10/11 x64. Cần Google Chrome cho Facebook và Microsoft Edge WebView2 cho giao diện. Bộ cài hỗ trợ cài WebView2 nếu thiếu. AI qua API cần Internet và API key riêng.

## Dữ liệu và tài khoản

- Bộ cài lưu dữ liệu trong `%LOCALAPPDATA%\NCT Studio\data`.
- Portable lưu dữ liệu cạnh ứng dụng.
- Mỗi tài khoản Facebook dùng hồ sơ Chrome riêng; chọn tài khoản cho từng nhóm.
- Bài riêng chỉ được lên lịch cho nhóm dùng đúng tài khoản đó.

## Mã nguồn mở

Mã nguồn NCT Studio được phát hành theo [MIT](LICENSE). Thành phần bên thứ ba giữ giấy phép riêng, xem [THIRD-PARTY.md](THIRD-PARTY.md).

## Cấu trúc mã nguồn

```text
source/             Backend Python, giao diện HTML/CSS/JS, assets và kiểm thử
native/Studio.cs    Cửa sổ desktop WinForms + WebView2
native/setup.iss    Cấu hình bộ cài Inno Setup
prepare_build.ps1   Tải công cụ build từ Microsoft NuGet và Inno Setup chính thức
build_release.py    Tạo gói desktop cùng Python runtime và thư viện
build.ps1           Build desktop và Setup trên Windows
sign_update.py      Công cụ ký manifest cập nhật dành cho người phát hành
```

## Chạy từ mã nguồn

Cách dễ nhất trên Windows: mở `source/start.bat`. Lần đầu script cài uv, Python 3.14 và các thư viện đã khóa trong `source/uv.lock`.

Nếu đã cài [uv](https://docs.astral.sh/uv/):

```powershell
uv sync --project source --locked --python 3.14
uv run --project source python source/app.py
```

Chạy trực tiếp `app.py` sẽ mở dashboard trên trình duyệt. Muốn cửa sổ EXE, dùng bản phát hành hoặc build theo phần dưới.

Không cần Ollama nếu dùng API. Nếu chọn model local, cài Ollama và tải model tương ứng trước.

## Build EXE và Setup

Yêu cầu Windows x64, uv/Python 3.14, .NET Framework 4.8 và Internet để tải công cụ. Script C# dùng trình biên dịch của .NET Framework trên Windows.

```powershell
.\prepare_build.ps1
.\build.ps1
```

Kết quả ở `output/NCT-Studio-Portable/NCT Studio.exe` và `output/NCT-Studio-Setup.exe`. Không tách riêng EXE khỏi runtime và các DLL của bản Portable. Tất cả thư mục công cụ, kết quả build và dữ liệu riêng đều được bỏ qua bởi `.gitignore`.

## Kiểm thử

Ví dụ nhóm kiểm thử đã dùng cho phần desktop, đa tài khoản và lịch:

```powershell
$env:PYTHONPATH = (Resolve-Path source).Path
uv run --project source python -m unittest discover -s source/tests -p test_deployment.py
uv run --project source python -m unittest discover -s source/tests -p test_facebook_accounts.py
uv run --project source python -m unittest discover -s source/tests -p test_online_update.py
```

Nếu chạy lệnh kiểm thử ở gốc repo, đặt `PYTHONPATH=source` để các kiểm thử nhập được module ứng dụng, hoặc chuyển vào `source` rồi chạy bằng Python trong môi trường đó.

Các kiểm thử này dùng dữ liệu tạm/mô phỏng. Bản EXE 1.1.0 đã được kiểm tra cài đặt và khởi động/thoát trên Windows với dữ liệu QA riêng. Không có cam kết mọi thao tác Facebook đều thành công; quyền đăng, phê duyệt và thay đổi giao diện phụ thuộc Facebook. Setup/EXE chưa có chứng thư ký mã Windows thương mại.


## Dành cho người phát hành

Xem [hướng dẫn ký và phát hành cập nhật](docs/RELEASING.md). Không đưa dữ liệu cá nhân hay khóa ký riêng lên Git; `.gitignore` đã loại các thư mục này.

## Nhập kho cũ sau lần mở đầu

Từ bản 1.1.1: vào **Cài đặt → Nhập dữ liệu cũ**, nhập đường dẫn thư mục `data` chứa `manager.sqlite3`, rồi chọn **Nhập dữ liệu và mở lại**. Kho hiện tại được sao lưu vào `data.backup-*` trước khi thay thế. Đây là thay thế kho, không gộp hai kho. Nguồn không bị sửa; cần nhập lại key/token và đăng nhập Facebook, lịch nhập về nháp.
