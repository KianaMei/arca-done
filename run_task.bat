@echo off
chcp 65001 >nul
title Arca Stitcher Task

set /p url="请输入 Arca.live 网址: "
if "%url%"=="" goto error

set output_dir=downloads\final_output

echo.
echo === 步骤 1: 下载 MP4 视频 ===
echo 正在启动爬虫...
python arca_scraper_dp.py "%url%" "%output_dir%"

if errorlevel 1 (
    echo.
    echo [错误] 下载脚本执行失败。
    pause
    exit /b
)

echo.
echo === 步骤 2: 拼接视频并转 GIF ===
python arca_stitcher.py "%output_dir%"

echo.
echo ==========================================
echo 全部完成！
echo 输出文件位于: %output_dir%\stitched_gif
echo ==========================================
pause
exit /b

:error
echo 未输入网址，退出。
pause
