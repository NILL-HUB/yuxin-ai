# 钰心AI 手机 App

基于 Capacitor 封装现有 Vue3 Web UI，目标平台 Android / iOS（后续）。

## 开发

```bash
cd ui && npm install && npm run build
cd ../mobile && npm install
npm run sync
```

## 运行

```bash
cd mobile
npm run android
# 或 npm run ios
```

## 能力说明

- 语音输入/朗读复用 Web 端 `audioToText` / TTS 接口。
- 图片上传、知识库、A2A、工作流等能力直接复用 `ui/`。
- 本机文件回收站/计算机控制/唤醒词属于桌面端能力，移动端按平台沙箱裁剪，
  不开放本地 Worker。
