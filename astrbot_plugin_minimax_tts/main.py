import aiohttp
import os
import time
import re
import logging
import traceback
import binascii
from typing import Optional
from astrbot.api.all import *
from astrbot.api.event import filter, AstrMessageEvent

logger = logging.getLogger("MiniMaxTTS")

# [tts_speak] 标签正则
TTS_SPEAK_PATTERN = re.compile(r'\[tts_speak\](.+?)\[/tts_speak\]', re.DOTALL | re.IGNORECASE)

@register("MiniMaxTTS", "YourName", "MiniMax TTS 语音合成插件", "1.2.0", "https://github.com/yourname/astrbot_plugin_minimax_tts")
class MiniMaxTTSPlugin(Star):
    """MiniMax TTS 插件 - 官方 API v2 - 修复标签处理逻辑"""
    
    API_URL = "https://api.minimaxi.com/v1/t2a_v2"
    API_URL_BJ = "https://api-bj.minimaxi.com/v1/t2a_v2"
    SUPPORTED_VOICES = ["female-shaonv", "male-qn", "female-jingdian", "male-jingdian"]
    _tts_tag_cache: dict = {}  # 全局缓存 [tts_speak] 内容

    def __init__(self, context: Context, config: dict | None = None):
        try:
            super().__init__(context, config=config)
        except Exception as e:
            logger.warning(f"super().__init__ 发生异常（可忽略）: {e}")
        
        if config:
            self.config = dict(config)
        else:
            self.config = {}

        default_config = {
            "api_key": "",
            "minimax_api_key": "",
            "model": "speech-2.6-turbo",
            "voice_id": "female-shaonv",
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0,
            "emotion": "neutral",
            "format": "mp3",
            "sample_rate": 32000,
            "output_format": "url"  # 使用 url 直接获取下载链接
        }
        
        for key, value in default_config.items():
            if key not in self.config:
                self.config[key] = value
        
        if not self.config.get('api_key') and self.config.get('minimax_api_key'):
            self.config['api_key'] = self.config['minimax_api_key']
        
        self.temp_dir = "/AstrBot/data/temp"
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
            
        key_status = '已配置' if self.config.get('api_key') else '缺失'
        logger.info(f"[MiniMaxTTS] 插件初始化完成。API Key 状态: {key_status}")

    def _save_audio_temp(self, audio_data: bytes) -> str:
        """保存音频到临时文件"""
        file_name = f"minimax_{int(time.time() * 1000)}.{self.config.get('format', 'mp3')}"
        file_path = os.path.join(self.temp_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(audio_data)
        return file_path

    async def _download_audio_from_url(self, url: str) -> Optional[bytes]:
        """从 URL 下载音频"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    else:
                        logger.error(f"[MiniMaxTTS] 音频下载失败: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"[MiniMaxTTS] 音频下载异常: {e}")
            return None

    async def _call_minimax_api(self, text: str) -> Optional[bytes]:
        """调用 MiniMax API（官方 v2 结构）"""
        logger.info(f"[MiniMaxTTS] 正在请求 API: {text[:30]}...")
        
        headers = {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json"
        }
        
        # 官方 v2 API 结构
        payload = {
            "model": self.config['model'],
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": self.config['voice_id'],
                "speed": self.config['speed'],
                "vol": self.config['vol'],
                "pitch": self.config['pitch']
            },
            "audio_setting": {
                "sample_rate": self.config.get('sample_rate', 32000),
                "format": self.config['format']
            }
        }
        
        # speech-2.6 以上支持情绪参数
        if "2.6" in self.config['model'] or "2.8" in self.config['model']:
            payload["voice_setting"]["emotion"] = self.config['emotion']
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.API_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    result = await resp.json()
                    
                    if resp.status == 200 and result.get("base_resp", {}).get("status_code") == 0:
                        logger.info("[MiniMaxTTS] API 请求成功")
                        
                        # 检查输出格式
                        output_fmt = self.config.get('output_format', 'url')
                        
                        if output_fmt == 'url' and result.get("data", {}).get("audio"):
                            # 返回下载 URL
                            audio_url = result["data"]["audio"]
                            logger.info(f"[MiniMaxTTS] 获取音频 URL: {audio_url}")
                            audio_data = await self._download_audio_from_url(audio_url)
                            return audio_data
                        else:
                            # hex 编码音频
                            hex_data = result.get("data", {}).get("audio")
                            if hex_data:
                                return binascii.unhexlify(hex_data)
                            else:
                                logger.error("[MiniMaxTTS] 响应中无音频数据")
                                return None
                    else:
                        error_msg = result.get("base_resp", {}).get("status_msg", "未知错误")
                        logger.error(f"[MiniMaxTTS] API 错误: {error_msg}")
                        return None
        except Exception as e:
            logger.error(f"[MiniMaxTTS] 网络请求异常: {e}")
            traceback.print_exc()
            return None

    @filter.regex(r"(?:^|.*?)mtts\s+(.+)")
    async def tts_command(self, event: AstrMessageEvent):
        """TTS 命令: /mtts <文本>"""
        msg = event.message_str.strip()
        m = re.search(r"(?:^|.*?)mtts\s+(.+)", msg, re.I)
        text = m.group(1).strip() if m else ""
        
        if not text:
            return event.plain_result("用法: /mtts <文本>")

        if not self.config.get('api_key'):
            logger.error("[MiniMaxTTS] API Key 未配置")
            return event.plain_result("❌ API Key 未配置，请检查配置文件")

        text = text.replace("-", " ")
        
        try:
            audio_data = await self._call_minimax_api(text)
            
            if audio_data:
                temp_path = self._save_audio_temp(audio_data)
                logger.info(f"[MiniMaxTTS] 音频文件已保存: {temp_path} ({len(audio_data)} bytes)")
                
                await event.send(MessageChain([Record(file=temp_path)]))
                return event
            else:
                logger.warning("[MiniMaxTTS] API 返回数据为空")
                return event.plain_result("❌ TTS 合成失败，请查看控制台日志")
                
        except Exception as e:
            logger.error(f"[MiniMaxTTS] 发生未捕获异常: {e}")
            return event.plain_result(f"❌ 发生错误: {str(e)}")

    @filter.on_decorating_result(priority=200)
    async def _pre_extract_tts_tag(self, event: AstrMessageEvent):
        """
        高优先级钩子：提前提取 [tts_speak] 标签内容，并保留标签外文字
        """
        try:
            result = event.get_result()
            if not result or not hasattr(result, "chain") or not result.chain:
                return

            # 检查是否是 LLM 响应
            try:
                is_llm = result.is_llm_result()
            except Exception:
                is_llm = getattr(result, "result_content_type", None) == 20
            if not is_llm:
                return

            umo = self._get_umo_key(event)
            
            # 1. 提取标签内的内容用于合成语音
            full_text = ""
            for comp in result.chain:
                if isinstance(comp, Plain) and getattr(comp, "text", None):
                    full_text += comp.text
                    
            match = TTS_SPEAK_PATTERN.search(full_text)
            if match:
                tts_content = match.group(1).strip()
                # 存入缓存
                MiniMaxTTSPlugin._tts_tag_cache[umo] = tts_content
                logger.debug(f"[TTS] 已缓存 sid={umo}, content={tts_content[:30]}...")
            else:
                # 如果没有找到标签，清理缓存并直接返回（不做任何修改）
                MiniMaxTTSPlugin._tts_tag_cache.pop(umo, None)
                return

            # 2. 【核心修复】清理标签本身，但保留标签外的文字
            # 使用正则替换，将 [tts_speak]...[/tts_speak] 替换为空，保留其他所有字符
            cleaned_text = TTS_SPEAK_PATTERN.sub('', full_text)
            
            # 防御性处理：如果替换后文本为空，给个默认值，避免消息为空
            if not cleaned_text.strip():
                cleaned_text = "..."

            # 3. 更新 Chain：将清理后的文本放回去
            new_chain = []
            for comp in result.chain:
                if isinstance(comp, Plain) and getattr(comp, "text", None):
                    # 创建一个新的 Plain 组件，内容是清理后的文本
                    comp.text = cleaned_text
                    new_chain.append(comp)
                elif not isinstance(comp, Plain):
                    # 非文本组件（如图片）直接保留
                    new_chain.append(comp)

            result.chain = new_chain
            logger.debug(f"[TTS] 已清理标签，传话筒将显示: {cleaned_text[:30]}...")

        except Exception as e:
            logger.debug(f"[TTS] _pre_extract_tts_tag error: {e}")

    @filter.on_decorating_result(priority=70)
    async def _tts_from_tag(self, event: AstrMessageEvent):
        """
        低优先级钩子：发送 TTS 语音
        """
        try:
            result = event.get_result()
            if not result or not hasattr(result, "chain"):
                return

            umo = self._get_umo_key(event)
            # 从缓存读取内容
            cached_tts = MiniMaxTTSPlugin._tts_tag_cache.pop(umo, None)
            if not cached_tts:
                return # 没有缓存内容，直接返回

            logger.info(f"[TTS] 开始合成标签内容: {cached_tts[:30]}...")

            # 1. 调用 API 合成语音
            audio_data = await self._call_minimax_api(cached_tts)
            if not audio_data:
                logger.warning("[TTS] API 返回数据为空")
                return

            # 2. 保存文件并发送
            temp_path = self._save_audio_temp(audio_data)
            logger.info(f"[TTS] 音频已保存: {temp_path} ({len(audio_data)} bytes)")
            
            # 发送语音消息
            await event.send(MessageChain([Record(file=temp_path)]))

        except Exception as e:
            logger.error(f"[TTS] _tts_from_tag error: {e}")

    def _get_umo_key(self, event: AstrMessageEvent) -> str:
        """获取会话唯一标识"""
        gid = ""
        try:
            gid = event.get_group_id()
        except Exception:
            gid = ""
        
        if gid and gid not in ("", "None", "null", "0"):
            return f"group_{gid}"
        return f"user_{event.get_sender_id()}"

    @filter.command("tts_voice")
    async def set_voice(self, event: AstrMessageEvent, voice_id: str = None):
        """设置音色"""
        if not voice_id:
            voices = "\n".join([f"• {v}" for v in self.SUPPORTED_VOICES])
            return event.plain_result(f"当前音色: {self.config['voice_id']}\n\n可用音色:\n{voices}")
        
        if voice_id not in self.SUPPORTED_VOICES:
            return event.plain_result(f"❌ 不支持的音色: {voice_id}")
        
        self.config['voice_id'] = voice_id
        return event.plain_result(f"✅ 音色已设置为: {voice_id}")

    @filter.command("tts_status")
    async def tts_status(self, event: AstrMessageEvent):
        """查看状态"""
        status = f"""
🎙️ MiniMax TTS 状态
----------------
模型: {self.config['model']}
音色: {self.config['voice_id']}
情绪: {self.config['emotion']}
语速: {self.config['speed']}
音量: {self.config['vol']}
输出: {self.config.get('output_format', 'url')}
API状态: {'✅ 已配置' if self.config.get('api_key') else '❌ 未配置'}
"""
        return event.plain_result(status)