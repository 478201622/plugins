# MiniMax TTS 插件 for AstrBot

基于 MiniMax 开放平台 TTS API 的语音合成插件。

## 功能特性

- ✅ 同步 HTTP 语音合成
- ✅ 支持多种模型（speech-2.8-hd, speech-2.8-turbo 等）
- ✅ 支持多种音色和情感
- ✅ 主备接口自动切换
- ✅ 完整的降级兜底机制
- ✅ 支持语气词标签（laughs, sighs 等）
- ✅ 支持停顿控制 `<#x#>`

## 安装

1. 将插件文件夹放入 `AstrBot/data/plugins/`
2. 重启 AstrBot 或重载插件
3. 在配置文件中设置 `api_key`

## 配置

在 `data/config/astrbot_plugin_minimax_tts.json` 中配置：

```json
{
  "api_key": "your-minimax-api-key",
  "model": "speech-2.8-hd",
  "voice_id": "male-qn-qingse",
  "speed": 1.0,
  "vol": 1.0,
  "pitch": 0,
  "emotion": "neutral",
  "format": "mp3"
}
```

## 命令

| 命令 | 说明 |
|------|------|
| `/tts <文本>` | 合成语音 |
| `/tts_voice [音色]` | 查看/设置音色 |
| `/tts_model [模型]` | 查看/设置模型 |
| `/tts_emotion [情感]` | 查看/设置情感 |
| `/tts_status` | 查看配置状态 |

## 音色列表

常用音色：
- `male-qn-qingse` - 青年男声（默认）
- `female-shaonv` - 少女声
- `female-yujie` - 御姐声
- `male-yangguang` - 阳光男声
- `female-chengshu` - 成熟女声
- `male-chengshu` - 成熟男声

## 语气词标签（仅 speech-2.8 系列）

在文本中插入以下标签实现自然语气：
- `(laughs)` - 笑声
- `(sighs)` - 叹气
- `(breath)` - 换气
- `(coughs)` - 咳嗽
- `(clear-throat)` - 清嗓子
- 更多见 MiniMax 文档

## 停顿控制

使用 `<#x#>` 控制停顿，x 为秒数（0.01-99.99）：

```
你好<#0.5#>世界  // 停顿 0.5 秒
```

## API 文档

https://platform.minimaxi.com/docs/api-reference/speech-t2a-http
