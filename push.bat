@echo off
cd /d d:\ai\notivo
echo ===== Notivo 推送到 GitHub =====
echo.
echo 正在推送代码到 https://github.com/xieyizhen0328/notivo
echo 如果弹出登录窗口，请用你的 GitHub 账号登录
echo.
git push -u origin main
echo.
echo ===== 完成！=====
echo 去 https://github.com/xieyizhen0328/notivo/actions 查看构建进度
pause
