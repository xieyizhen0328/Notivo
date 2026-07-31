# Notivo APK 构建指南

## 本地一键构建（国内网络可用）

### 前置准备（只需安装一次）

**第 1 步：安装 JDK 17**

清华镜像（国内快）：https://mirrors.tuna.tsinghua.edu.cn/Adoptium/17/jdk/windows/x64/

下载 `jdk-17.0.17+10_windows-x64_bin.msi`，双击安装，全部默认选项。

**第 2 步：安装 Android SDK 命令行工具**

官网（国内可访问）：https://developer.android.google.cn/studio

往下翻到"仅命令行工具"，下载 Windows 版 zip。

解压到 `C:\Android\cmdline-tools\latest\`，
确保路径 `C:\Android\cmdline-tools\latest\bin\sdkmanager.bat` 存在。

**第 3 步：设置环境变量**

Win+R → 输入 `sysdm.cpl` → 高级 → 环境变量 → 新建系统变量：

| 变量名 | 值 |
|--------|-----|
| JAVA_HOME | C:\Program Files\Eclipse Adoptium\jdk-17.0.17.10-hotspot\ |
| ANDROID_HOME | C:\Android |

Path 里添加: `%ANDROID_HOME%\cmdline-tools\latest\bin`

**第 4 步：安装 Android SDK 组件**

打开新的 cmd 窗口，运行：
```bash
sdkmanager --licenses
sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"
```

### 构建 APK

双击 `d:\ai\notivo\local-build.bat`，自动完成构建。

APK 输出位置：`d:\ai\notivo\android\app\build\outputs\apk\debug\app-debug.apk`

---

## 使用 Android Studio（一键安装，最简单）

1. 下载：https://developer.android.google.cn/studio
2. 安装，全部默认
3. 打开 Android Studio → Open → 选择 `d:\ai\notivo\android` 目录
4. Build → Build Bundle(s) / APK(s) → Build APK(s)
5. 右下角点 `locate` 找到 APK 文件
