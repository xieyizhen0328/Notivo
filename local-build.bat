@echo off
echo ========================================
echo   Notivo APK 本地构建工具
echo ========================================
echo.

:: Step 1: Check Java
echo [1/4] 检查 Java...
java -version 2>nul
if %ERRORLEVEL% EQU 0 (
    echo   Java 已安装
    goto :check_sdk
)
echo   Java 未安装，正在下载 JDK 17...
echo   请手动下载并安装: https://mirrors.tuna.tsinghua.edu.cn/Adoptium/17/jdk/windows/x64/
echo   下载 jdk-17_windows-x64_bin.msi 双击安装，全部默认选项
echo   安装完成后重新运行此脚本
pause
exit /b 1

:check_sdk
:: Step 2: Check Android SDK
echo.
echo [2/4] 检查 Android SDK...
if exist "%ANDROID_HOME%" (
    echo   ANDROID_HOME = %ANDROID_HOME%
    goto :build
)
if exist "%LOCALAPPDATA%\Android\Sdk" (
    set ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk
    echo   ANDROID_HOME = %ANDROID_HOME%
    goto :build
)
echo   Android SDK 未安装
echo   请下载命令行工具: https://developer.android.google.cn/studio
echo   或者直接安装 Android Studio（推荐）: https://developer.android.google.cn/studio
echo   安装后重新运行此脚本
pause
exit /b 1

:build
:: Step 3: Set up local.properties
echo.
echo [3/4] 配置 Android 项目...
echo sdk.dir=%ANDROID_HOME:\=/%> android\local.properties
echo   local.properties 已创建

:: Step 4: Build
echo.
echo [4/4] 开始构建 APK...
cd android
call gradlew.bat assembleDebug

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ===== 构建失败！=====
    pause
    exit /b 1
)

echo.
echo ===== 构建成功！=====
echo APK 位置: android\app\build\outputs\apk\debug\app-debug.apk
echo.
echo 把这个 apk 文件传到手机安装即可
pause
