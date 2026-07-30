# Notivo APK 构建指南

## GitHub Actions 在线构建（推荐，无需 Android Studio）

### 1. 推送到 GitHub

```bash
cd d:\ai\notivo

# 创建 GitHub 仓库（在 github.com 上新建一个空仓库，不要勾选 README）

git remote add origin https://github.com/你的用户名/notivo.git
git branch -M main
git commit -m "Notivo v1.0"

# 重要：先把 .env 加入 .gitignore（避免泄露 API Key）
echo ".env" >> .gitignore
git add .gitignore
git commit -m "exclude .env"

git push -u origin main
```

### 2. 自动构建

推送后 GitHub Actions 自动触发构建。约 3-5 分钟后，APK 出现在：

**GitHub → Actions → 最新 workflow run → Artifacts → `notivo-debug`**

### 3. 下载安装

下载 `app-debug.apk` → 传到手机 → 打开安装。

**注意**：首次安装需要在手机设置中允许"未知来源"安装。

---

## 手动触发构建

在 GitHub 仓库页面：
**Actions → Build APK → Run workflow**

---

## APK 使用说明

APK 中的 `API_BASE` 默认为 `http://localhost:8000`。

手机无法访问 localhost，部署前需要：

1. **方案 A**：手机和电脑同一 WiFi → 将 `API_BASE` 改为电脑局域网 IP
   - 电脑 IP 查看：`ipconfig` → 找 IPv4 地址（如 `192.168.1.100`）
   - 修改 `www/index.html` 顶部 `API_BASE` 为 `http://192.168.1.100:8000`
   - 重新 `npm run sync && git push` 触发构建

2. **方案 B**：部署后端到公网服务器 → `API_BASE` 改为服务器域名

3. **方案 C**：使用 ngrok 等内网穿透工具临时暴露后端

---

## 本地构建（备选）

安装 [Android Studio](https://developer.android.com/studio) 后：

```bash
npm run sync          # 同步 web 资源
npm run open:android  # 打开 Android Studio
# Android Studio → Build → Build APK(s)
# 输出: android\app\build\outputs\apk\debug\app-debug.apk
```
