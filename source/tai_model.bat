@echo off
setlocal
chcp 65001 >nul
where ollama >nul 2>&1
if errorlevel 1 (
  echo Chua tim thay Ollama. Cai Ollama tai https://ollama.com/download/windows
  start "" "https://ollama.com/download/windows"
  pause
  exit /b 1
)
echo Dang tai qwen3:8b ve PC. Can mang va dung luong trong. Lan dau co the lau.
ollama pull qwen3:8b
if errorlevel 1 (
  echo Tai that bai. Mo Ollama va kiem tra mang, sau do chay lai.
) else (
  echo Da tai xong. Chon qwen3:8b trong NCT Group Manager.
)
pause
