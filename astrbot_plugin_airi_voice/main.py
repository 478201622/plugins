from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import re
import random
import aiohttp
from pydantic import Field
from pydantic.dataclasses import dataclass
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter, MessageChain
from astrbot.api.message_components import Record, Video, Reply
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

# 语音文件扩展名
VOICE_EXT = {".mp3", ".wav", ".ogg", ".silk", ".amr"}
# 视频文件扩展名
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".flv", ".m4v", ".3gp"}
# 所有支持的扩展名
ALLOWED_EXT = VOICE_EXT | VIDEO_EXT

PAGE_SIZE = 15


def get_media_type(file_path: str) -> str:
    """判断文件类型：voice 或 video"""
    ext = Path(file_path).suffix.lower()
    if ext in VOICE_EXT:
        return "voice"
    elif ext in VIDEO_EXT:
        return "video"
    return "unknown"


def get_component_for_file(file_path: str):
    """根据文件路径返回对应的消息组件类"""
    media_type = get_media_type(file_path)
    if media_type == "voice":
        return Record
    elif media_type == "video":
        return Video
    return None


@dataclass
class AiriListAllMediaTool(FunctionTool[AstrAgentContext]):
    """列出当前插件中所有可用的语音和视频名称。"""
    name: str = "airi_list_all_media"
    description: str = "列出本插件加载的全部语音和视频名称，供 LLM 选择使用。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "required": [],
        }
    )
    plugin: Any = None

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        if not self.plugin or getattr(self.plugin, "trigger_mode", None) != "llm":
            return "当前未开启 LLM 触发模式，本工具暂不可用。"
        if not self.plugin.voice_map and not self.plugin.video_map:
            return "当前没有可用媒体。"
        
        voices = sorted(self.plugin.voice_map.keys())
        videos = sorted(self.plugin.video_map.keys())
        
        result = []
        if voices:
            result.append(f"【语音】({len(voices)}个):")
            result.append("\n".join(f"  • {k}" for k in voices))
        if videos:
            result.append(f"【视频】({len(videos)}个):")
            result.append("\n".join(f"  • {k}" for k in videos))
        
        return "当前可用媒体名称列表：\n\n" + "\n\n".join(result)


@dataclass
class AiriSearchMediaTool(FunctionTool[AstrAgentContext]):
    """根据关键词筛选媒体名称。"""
    name: str = "airi_search_media"
    description: str = (
        "根据用户给出的关键词，在本插件的媒体库中筛选匹配的语音或视频名称。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "用户给出的媒体关键词，用于模糊匹配名称。",
                }
            },
            "required": ["keyword"],
        }
    )
    plugin: Any = None

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        if not self.plugin or getattr(self.plugin, "trigger_mode", None) != "llm":
            return "当前未开启 LLM 触发模式，本工具暂不可用。"
        if not self.plugin.voice_map and not self.plugin.video_map:
            return "当前没有可用媒体。"
        keyword = (kwargs.get("keyword") or "").strip()
        if not keyword:
            return "请提供要搜索的媒体关键词。"
        keyword_lower = keyword.lower()
        
        matched_voices = [
            name for name in self.plugin.voice_map.keys() if keyword_lower in name.lower()
        ]
        matched_videos = [
            name for name in self.plugin.video_map.keys() if keyword_lower in name.lower()
        ]
        
        if not matched_voices and not matched_videos:
            return f"未找到包含「{keyword}」的媒体名称。"
        
        result = []
        if matched_voices:
            matched_voices.sort()
            result.append(f"【匹配语音】({len(matched_voices)}个):")
            result.append("\n".join(f"  • {k}" for k in matched_voices))
        if matched_videos:
            matched_videos.sort()
            result.append(f"【匹配视频】({len(matched_videos)}个):")
            result.append("\n".join(f"  • {k}" for k in matched_videos))
        
        return f"根据关键词「{keyword}」筛选到的媒体：\n\n" + "\n\n".join(result)


@dataclass
class AiriSendMediaTool(FunctionTool[AstrAgentContext]):
    """根据指定名称直接向当前会话发送语音或视频。"""
    name: str = "airi_send_media"
    description: str = (
        "根据指定的媒体名称，直接向当前会话发送对应的语音或视频消息。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要发送的媒体名称，必须是已存在的媒体列表中的一个。",
                }
            },
            "required": ["name"],
        }
    )
    plugin: Any = None

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        if not self.plugin or getattr(self.plugin, "trigger_mode", None) != "llm":
            return "当前未开启 LLM 触发模式，本工具暂不可用。"
        if not self.plugin.voice_map and not self.plugin.video_map:
            return "当前没有可用媒体。"
        name = (kwargs.get("name") or "").strip()
        if not name:
            return "请提供要发送的媒体名称。"
        
        # 先查找语音，再查找视频
        path = self.plugin.voice_map.get(name)
        media_type = "voice"
        if not path:
            path = self.plugin.video_map.get(name)
            media_type = "video"
        
        if not path:
            return f"「{name}」不存在，请先使用列出/搜索工具确认可用名称。"
        
        try:
            agent_ctx = context.context.context
            event = context.context.event
        except Exception:
            agent_ctx = None
            event = None
        if agent_ctx is None or event is None:
            return f"无法获取当前会话上下文，未能发送「{name}」。"
        
        try:
            ComponentClass = get_component_for_file(path)
            if ComponentClass is None:
                return f"不支持的文件类型：{path}"
            
            await agent_ctx.send_message(
                event.unified_msg_origin,
                MessageChain([ComponentClass.fromFileSystem(path)]),
            )
            logger.debug(f"[AiriVoice] LLM 工具发送{media_type}：'{name}' → {path}")
            return ""
        except FileNotFoundError as e:
            logger.error(f"[AiriVoice] 文件不存在（LLM 工具） '{name}': {e}")
            return f"媒体文件不存在：{name}"
        except Exception as e:
            logger.error(f"[AiriVoice] LLM 工具发送失败 '{name}': {e}")
            return f"发送失败：{type(e).__name__}"


@register(
    "airi_voice",
    "lidure",
    "输入关键词发送对应语音或视频",
    "2.4",
    "https://github.com/Lidure/astrbot_plugin_airi_voice",
)
class AiriVoice(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)

        self.plugin_dir = Path(__file__).parent
        self.voice_dir = self.plugin_dir / "voices"
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        
        # 新增视频目录
        self.video_dir = self.plugin_dir / "videos"
        self.video_dir.mkdir(parents=True, exist_ok=True)

        self.data_dir = StarTools.get_data_dir("astrbot_plugin_airi_voice")
        self.user_added_dir = self.data_dir / "user_added"
        self.user_added_dir.mkdir(parents=True, exist_ok=True)
        
        # 新增用户添加的视频目录
        self.user_added_video_dir = self.data_dir / "user_added_videos"
        self.user_added_video_dir.mkdir(parents=True, exist_ok=True)
        
        self.extra_voice_dir = self.data_dir / "extra_voices"
        self.extra_voice_dir.mkdir(parents=True, exist_ok=True)
        
        # 新增额外视频目录
        self.extra_video_dir = self.data_dir / "extra_videos"
        self.extra_video_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[AiriVoice] 数据目录：{self.data_dir}")

        self.config = config or {}
        self.trigger_mode = self.config.get("trigger_mode", "direct")
        if self.trigger_mode not in {"prefix", "direct", "llm"}:
            logger.warning(f"[AiriVoice] 无效 trigger_mode，强制使用 direct")
            self.trigger_mode = "direct"

        self.admin_mode = self.config.get("admin_mode", "whitelist")
        if self.admin_mode not in {"all", "admin", "whitelist"}:
            self.admin_mode = "whitelist"

        whitelist_raw = self.config.get("admin_whitelist", "")
        if isinstance(whitelist_raw, str):
            self.admin_whitelist: Set[str] = set(
                line.strip() for line in whitelist_raw.splitlines() if line.strip()
            )
        elif isinstance(whitelist_raw, list):
            self.admin_whitelist: Set[str] = set(str(x).strip() for x in whitelist_raw if str(x).strip())
        else:
            self.admin_whitelist: Set[str] = set()

        self.llm_select_mode = self.config.get("llm_select_mode", "list")
        if self.llm_select_mode not in {"list", "keyword"}:
            logger.warning(f"[AiriVoice] 无效 llm_select_mode，强制使用 list")
            self.llm_select_mode = "list"

        # bot 回复自动追加语音/视频开关
        self.auto_reply_voice_enabled = self.config.get("auto_reply_voice_on_bot_message", False)

        # 语音和视频映射表
        self.voice_map: Dict[str, str] = {}
        self.video_map: Dict[str, str] = {}
        self.sorted_keys: List[str] = []
        self.sorted_video_keys: List[str] = []

        self._load_local_voices()
        self._load_local_videos()
        self._load_user_added_voices()
        self._load_user_added_videos()
        self._load_web_voices(self.config)
        self._load_web_videos(self.config)
        self._update_sorted_keys()

        self.last_pool_len = len(self.config.get("extra_voice_pool", []))
        self.last_video_pool_len = len(self.config.get("extra_video_pool", []))

        if self.trigger_mode == "llm":
            llm_tools = []
            if self.llm_select_mode == "list":
                llm_tools.append(AiriListAllMediaTool(plugin=self))
            else:
                llm_tools.append(AiriSearchMediaTool(plugin=self))
            llm_tools.append(AiriSendMediaTool(plugin=self))
            try:
                self.context.add_llm_tools(*llm_tools)
                logger.info(
                    f"[AiriVoice] 已为 LLM 注册 {len(llm_tools)} 个媒体工具，模式：{self.llm_select_mode}"
                )
            except Exception as e:
                logger.error(f"[AiriVoice] 注册 LLM 工具失败：{e}")

        if self.auto_reply_voice_enabled:
            logger.info("[AiriVoice] 已启用 bot 回复自动追加媒体功能")

        total_voices = len(self.voice_map)
        total_videos = len(self.video_map)
        logger.info(f"[AiriVoice] 初始化完成，共 {total_voices} 个语音、{total_videos} 个视频，权限模式：{self.admin_mode}")


    def _get_user_id(self, event: AstrMessageEvent) -> Optional[str]:
        try:
            return event.get_sender_id()
        except (AttributeError, TypeError):
            pass
        try:
            return event.message_obj.sender.user_id
        except AttributeError:
            pass
        user_id = getattr(event, 'sender_id', None) or getattr(event, 'user_id', None)
        return str(user_id) if user_id else None

    def _get_reply_id(self, event: AstrMessageEvent) -> Optional[int]:
        for seg in event.get_messages():
            if isinstance(seg, Reply):
                try:
                    return int(seg.id)
                except (ValueError, TypeError):
                    pass
        return None

    async def _get_media_url(self, event: AstrMessageEvent) -> tuple[Optional[str], str]:
        """获取引用消息中的媒体URL和类型"""
        chain = event.get_messages()
        url = None
        media_type = "unknown"
        
        def extract_media_url(seg):
            url_ = (
                getattr(seg, "url", None)
                or getattr(seg, "file", None)
                or getattr(seg, "path", None)
            )
            return url_ if url_ and str(url_).startswith("http") else None

        reply_seg = next((seg for seg in chain if isinstance(seg, Reply)), None)
        if reply_seg and hasattr(reply_seg, 'chain') and reply_seg.chain:
            for seg in reply_seg.chain:
                if isinstance(seg, Record):
                    url = extract_media_url(seg)
                    media_type = "voice"
                    if url:
                        break
                elif isinstance(seg, Video):
                    url = extract_media_url(seg)
                    media_type = "video"
                    if url:
                        break

        if url is None and hasattr(event, 'bot'):
            if msg_id := self._get_reply_id(event):
                try:
                    raw = await event.bot.get_msg(message_id=msg_id)
                    messages = raw.get("message", [])
                    for seg in messages:
                        if isinstance(seg, dict):
                            if seg.get("type") == "record":
                                if seg_url := seg.get("data", {}).get("url"):
                                    url = seg_url
                                    media_type = "voice"
                                    break
                            elif seg.get("type") == "video":
                                if seg_url := seg.get("data", {}).get("url"):
                                    url = seg_url
                                    media_type = "video"
                                    break
                except Exception as e:
                    logger.error(f"[AiriVoice] 获取引用消息失败：{e}")
        return url, media_type

    async def _download_media(self, url: str) -> Optional[bytes]:
        try:
            async with aiohttp.ClientSession() as client:
                response = await client.get(url)
                return await response.read()
        except Exception as e:
            logger.error(f"[AiriVoice] 下载媒体失败：{e}")
            return None

    def _get_file_ext_from_url(self, url: str) -> str:
        url_lower = url.lower()
        # 语音扩展名
        if ".wav" in url_lower:
            return ".wav"
        elif ".ogg" in url_lower:
            return ".ogg"
        elif ".silk" in url_lower:
            return ".silk"
        elif ".amr" in url_lower:
            return ".amr"
        # 视频扩展名
        elif ".mp4" in url_lower:
            return ".mp4"
        elif ".mov" in url_lower:
            return ".mov"
        elif ".webm" in url_lower:
            return ".webm"
        elif ".mkv" in url_lower:
            return ".mkv"
        elif ".avi" in url_lower:
            return ".avi"
        elif ".flv" in url_lower:
            return ".flv"
        elif ".m4v" in url_lower:
            return ".m4v"
        elif ".3gp" in url_lower:
            return ".3gp"
        return ".mp3"  # 默认

    def _update_sorted_keys(self):
        self.sorted_keys = sorted(self.voice_map.keys())
        self.sorted_video_keys = sorted(self.video_map.keys())

    def _load_local_voices(self):
        count = 0
        for file_path in self.voice_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in VOICE_EXT:
                keyword = file_path.stem.strip()
                if keyword:
                    self.voice_map[keyword] = str(file_path)
                    count += 1
        if count > 0:
            logger.info(f"[AiriVoice] 从本地加载 {count} 个语音")

    def _load_local_videos(self):
        count = 0
        for file_path in self.video_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXT:
                keyword = file_path.stem.strip()
                if keyword:
                    self.video_map[keyword] = str(file_path)
                    count += 1
        if count > 0:
            logger.info(f"[AiriVoice] 从本地加载 {count} 个视频")

    def _load_user_added_voices(self):
        count = 0
        for file_path in self.user_added_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in VOICE_EXT:
                keyword = file_path.stem.strip()
                if keyword:
                    if keyword in self.voice_map:
                        logger.warning(f"[AiriVoice] 用户添加关键词冲突：'{keyword}' 已存在，将覆盖")
                    self.voice_map[keyword] = str(file_path)
                    count += 1
        if count > 0:
            logger.info(f"[AiriVoice] 从用户添加目录加载 {count} 个语音")

    def _load_user_added_videos(self):
        count = 0
        for file_path in self.user_added_video_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXT:
                keyword = file_path.stem.strip()
                if keyword:
                    if keyword in self.video_map:
                        logger.warning(f"[AiriVoice] 用户添加视频关键词冲突：'{keyword}' 已存在，将覆盖")
                    self.video_map[keyword] = str(file_path)
                    count += 1
        if count > 0:
            logger.info(f"[AiriVoice] 从用户添加目录加载 {count} 个视频")


    def _load_web_voices(self, config: dict = None):
        if config is None:
            return
        extra_pool = config.get("extra_voice_pool", [])
        if not extra_pool:
            return
        logger.debug(f"[AiriVoice] 网页相对路径池：{extra_pool}")
        loaded_voice = 0
        loaded_video = 0
        data_dir_resolved = self.data_dir.resolve()
        for rel_path in extra_pool:
            if not isinstance(rel_path, str) or not rel_path.strip():
                continue
            try:
                abs_path = (self.data_dir / rel_path).resolve()
                if not abs_path.is_relative_to(data_dir_resolved):
                    logger.warning(f"[AiriVoice] 检测到非法路径：{rel_path}")
                    continue
            except (ValueError, OSError) as e:
                logger.warning(f"[AiriVoice] 路径解析失败：{rel_path} - {e}")
                continue
            if abs_path.exists() and abs_path.is_file():
                ext = abs_path.suffix.lower()
                keyword = abs_path.stem.strip()
                if not keyword:
                    continue
                if ext in VOICE_EXT:
                    self.voice_map[keyword] = str(abs_path)
                    loaded_voice += 1
                    logger.debug(f"[AiriVoice] 网页加载语音：'{keyword}' → {abs_path}")
                elif ext in VIDEO_EXT:
                    self.video_map[keyword] = str(abs_path)
                    loaded_video += 1
                    logger.debug(f"[AiriVoice] 网页加载视频：'{keyword}' → {abs_path}")
                else:
                    logger.warning(f"[AiriVoice] 忽略不支持的文件类型：{abs_path}")
            else:
                logger.warning(f"[AiriVoice] 文件不存在：{abs_path} (相对：{rel_path})")
        if loaded_voice > 0:
            logger.info(f"[AiriVoice] 从网页配置加载 {loaded_voice} 个额外语音")
        if loaded_video > 0:
            logger.info(f"[AiriVoice] 从网页配置加载 {loaded_video} 个额外视频")

    def _load_web_videos(self, config: dict = None):
        if config is None:
            return
        extra_pool = config.get("extra_video_pool", [])
        if not extra_pool:
            return
        logger.debug(f"[AiriVoice] 视频网页相对路径池：{extra_pool}")
        loaded = 0
        data_dir_resolved = self.data_dir.resolve()
        for rel_path in extra_pool:
            if not isinstance(rel_path, str) or not rel_path.strip():
                continue
            try:
                abs_path = (self.data_dir / rel_path).resolve()
                if not abs_path.is_relative_to(data_dir_resolved):
                    logger.warning(f"[AiriVoice] 检测到非法视频路径：{rel_path}")
                    continue
            except (ValueError, OSError) as e:
                logger.warning(f"[AiriVoice] 视频路径解析失败：{rel_path} - {e}")
                continue
            if abs_path.exists() and abs_path.is_file():
                if abs_path.suffix.lower() not in VIDEO_EXT:
                    logger.warning(f"[AiriVoice] 忽略非视频文件：{abs_path}")
                    continue
                keyword = abs_path.stem.strip()
                if keyword:
                    self.video_map[keyword] = str(abs_path)
                    loaded += 1
                    logger.debug(f"[AiriVoice] 网页加载视频：'{keyword}' → {abs_path}")
            else:
                logger.warning(f"[AiriVoice] 视频文件不存在：{abs_path} (相对：{rel_path})")
        if loaded > 0:
            logger.info(f"[AiriVoice] 从网页配置加载 {loaded} 个额外视频")

    def _check_admin(self, event: AstrMessageEvent) -> bool:
        if self.admin_mode == "all":
            return True
        if self.admin_mode == "admin":
            if getattr(event, 'is_admin', False) or getattr(event, 'is_master', False):
                return True
            try:
                role = event.get_platform_user_role()
                if role in ('admin', 'owner', 'master'):
                    return True
            except AttributeError:
                pass
            return False
        if self.admin_mode == "whitelist":
            user_id = self._get_user_id(event)
            if user_id and user_id in self.admin_whitelist:
                return True
            uname = getattr(event, 'sender_name', None) or getattr(event, 'nickname', None)
            if uname and uname in self.admin_whitelist:
                return True
            return False
        return False

    async def _send_media_result(self, event: AstrMessageEvent, path: str, name: str):
        """统一发送媒体文件（语音或视频）"""
        try:
            ComponentClass = get_component_for_file(path)
            if ComponentClass is None:
                logger.error(f"[AiriVoice] 不支持的文件类型：{path}")
                yield event.plain_result(f"不支持的文件类型：{Path(path).suffix}")
                return
            
            yield event.chain_result([ComponentClass.fromFileSystem(path)])
            logger.debug(f"[AiriVoice] 发送媒体：'{name}' → {path}")
        except FileNotFoundError as e:
            logger.error(f"[AiriVoice] 文件不存在 '{name}': {e}")
            yield event.plain_result(f"媒体文件不存在")
        except Exception as e:
            logger.error(f"[AiriVoice] 发送失败 '{name}': {e}")
            yield event.plain_result(f"发送失败：{type(e).__name__}")


    @filter.regex(r"^\s*.+\s*$")
    async def media_handler(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        if not text:
            return

        # 检查配置变化
        current_pool_len = len(self.config.get("extra_voice_pool", []))
        current_video_pool_len = len(self.config.get("extra_video_pool", []))
        
        if current_pool_len > self.last_pool_len or current_video_pool_len > self.last_video_pool_len:
            logger.info("[AiriVoice] 检测到网页配置变化，自动刷新媒体列表")
            self._load_web_voices(self.config)
            self._load_web_videos(self.config)
            self._update_sorted_keys()
            self.last_pool_len = current_pool_len
            self.last_video_pool_len = current_video_pool_len

        keyword = text
        if self.trigger_mode == "prefix":
            match = re.search(r"^#voice\s+(.+)", text, re.I)
            if not match:
                match = re.search(r"^#video\s+(.+)", text, re.I)
            if not match:
                return
            keyword = match.group(1).strip()

        # 先查找语音，再查找视频
        matched_path = self.voice_map.get(keyword)
        if matched_path:
            async for result in self._send_media_result(event, matched_path, keyword):
                yield result
            return
        
        matched_path = self.video_map.get(keyword)
        if matched_path:
            async for result in self._send_media_result(event, matched_path, keyword):
                yield result
            return


    @filter.command("voice.add")
    async def voice_add(self, event: AstrMessageEvent, name: str):
        async for result in self._add_media(event, name, "voice"):
            yield result

    @filter.command("video.add")
    async def video_add(self, event: AstrMessageEvent, name: str):
        async for result in self._add_media(event, name, "video"):
            yield result

    async def _add_media(self, event: AstrMessageEvent, name: str, media_type: str):
        if not self._check_admin(event):
            yield event.plain_result("❌ 权限不足：此命令仅限管理员使用")
            return
        if not self._get_reply_id(event):
            yield event.plain_result("❌ 请引用一条语音或视频消息后再使用此命令")
            return
        if not name or name.strip() == "":
            type_name = "语音" if media_type == "voice" else "视频"
            yield event.plain_result(f"❌ 请提供{type_name}名称，例如：/{media_type}.add 名称")
            return
        
        name = name.strip()
        
        # 检查名称是否已存在
        if name in self.voice_map or name in self.video_map:
            yield event.plain_result(f"⚠️ 「{name}」已存在，如需覆盖请先删除旧媒体")
            return
        
        media_url, detected_type = await self._get_media_url(event)
        if not media_url:
            yield event.plain_result("❌ 未能从引用的消息中提取到媒体，请确保引用的是语音或视频消息")
            return
        
        # 如果检测到类型与指定类型不符，给出警告
        if detected_type != "unknown" and detected_type != media_type:
            logger.warning(f"[AiriVoice] 检测到媒体类型为{detected_type}，但用户指定为{media_type}")
        
        logger.debug(f"[AiriVoice] 获取到媒体 URL: {media_url}, 类型: {detected_type}")
        media_data = await self._download_media(media_url)
        if not media_data:
            yield event.plain_result("❌ 媒体下载失败，请稍后重试")
            return
        
        ext = self._get_file_ext_from_url(media_url)
        
        # 根据类型选择保存目录
        if media_type == "voice":
            file_path = self.user_added_dir / f"{name}{ext}"
            target_map = self.voice_map
        else:
            file_path = self.user_added_video_dir / f"{name}{ext}"
            target_map = self.video_map
        
        try:
            with open(file_path, "wb") as f:
                f.write(media_data)
            target_map[name] = str(file_path)
            self._update_sorted_keys()
            type_name = "语音" if media_type == "voice" else "视频"
            yield event.plain_result(f"✅ {type_name}「{name}」添加成功！\n📁 文件：{name}{ext}\n💾 大小：{len(media_data) / 1024:.2f} KB")
        except Exception as e:
            logger.error(f"[AiriVoice] 保存媒体失败：{e}")
            yield event.plain_result(f"❌ 保存失败：{str(e)}")

    @filter.command("voice.delete")
    async def voice_delete(self, event: AstrMessageEvent, name: str):
        async for result in self._delete_media(event, name, "voice"):
            yield result

    @filter.command("video.delete")
    async def video_delete(self, event: AstrMessageEvent, name: str):
        async for result in self._delete_media(event, name, "video"):
            yield result

    async def _delete_media(self, event: AstrMessageEvent, name: str, media_type: str):
        if not self._check_admin(event):
            yield event.plain_result("❌ 权限不足：此命令仅限管理员使用")
            return
        
        if media_type == "voice":
            target_map = self.voice_map
            target_dir = self.user_added_dir
        else:
            target_map = self.video_map
            target_dir = self.user_added_video_dir
        
        if name not in target_map:
            type_name = "语音" if media_type == "voice" else "视频"
            yield event.plain_result(f"❌ {type_name}「{name}」不存在")
            return
        
        file_path = Path(target_map[name])
        if not str(file_path.resolve()).startswith(str(target_dir.resolve())):
            type_name = "语音" if media_type == "voice" else "视频"
            yield event.plain_result(f"⚠️ 只能删除通过 /{media_type}.add 添加的{type_name}，本地和网页上传的文件请手动管理")
            return
        
        try:
            file_path.unlink()
            del target_map[name]
            self._update_sorted_keys()
            type_name = "语音" if media_type == "voice" else "视频"
            yield event.plain_result(f"✅ {type_name}「{name}」已删除")
        except Exception as e:
            logger.error(f"[AiriVoice] 删除媒体失败：{e}")
            yield event.plain_result(f"❌ 删除失败：{str(e)}")


    @filter.command("voice.list")
    async def voice_list(self, event: AstrMessageEvent, page: int = 1):
        async for result in self._list_media(event, page, "voice"):
            yield result

    @filter.command("video.list")
    async def video_list(self, event: AstrMessageEvent, page: int = 1):
        async for result in self._list_media(event, page, "video"):
            yield result

    async def _list_media(self, event: AstrMessageEvent, page: int, media_type: str):
        if media_type == "voice":
            target_keys = self.sorted_keys
            target_map = self.voice_map
            type_name = "语音"
        else:
            target_keys = self.sorted_video_keys
            target_map = self.video_map
            type_name = "视频"
        
        if not target_keys:
            yield event.plain_result(f"当前没有可用{type_name}～")
            return
        
        total = len(target_keys)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
        
        start = (page - 1) * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        
        items = target_keys[start:end]
        lines = [f"📋 {type_name}列表 (第 {page}/{total_pages} 页，共 {total} 个)"]
        lines.append("-" * 30)
        
        for i, name in enumerate(items, start + 1):
            path = target_map[name]
            file_size = Path(path).stat().st_size / 1024
            lines.append(f"{i}. {name} ({file_size:.1f} KB)")
        
        lines.append("-" * 30)
        lines.append(f"使用 /{media_type}.list <页码> 查看更多")
        
        yield event.plain_result("\n".join(lines))

    @filter.command("voice.search")
    async def voice_search(self, event: AstrMessageEvent, keyword: str):
        async for result in self._search_media(event, keyword, "voice"):
            yield result

    @filter.command("video.search")
    async def video_search(self, event: AstrMessageEvent, keyword: str):
        async for result in self._search_media(event, keyword, "video"):
            yield result

    async def _search_media(self, event: AstrMessageEvent, keyword: str, media_type: str):
        if not keyword or keyword.strip() == "":
            type_name = "语音" if media_type == "voice" else "视频"
            yield event.plain_result(f"❌ 请提供搜索关键词，例如：/{media_type}.search 关键词")
            return
        
        keyword = keyword.strip().lower()
        
        if media_type == "voice":
            target_keys = self.sorted_keys
            target_map = self.voice_map
            type_name = "语音"
        else:
            target_keys = self.sorted_video_keys
            target_map = self.video_map
            type_name = "视频"
        
        if not target_keys:
            yield event.plain_result(f"当前没有可用{type_name}～")
            return
        
        matched = [name for name in target_keys if keyword in name.lower()]
        
        if not matched:
            yield event.plain_result(f"未找到包含「{keyword}」的{type_name}")
            return
        
        lines = [f"🔍 {type_name}搜索结果：「{keyword}」"]
        lines.append("-" * 30)
        
        for name in matched[:20]:  # 最多显示20个
            path = target_map[name]
            file_size = Path(path).stat().st_size / 1024
            lines.append(f"• {name} ({file_size:.1f} KB)")
        
        if len(matched) > 20:
            lines.append(f"\n... 还有 {len(matched) - 20} 个结果")
        
        lines.append("-" * 30)
        lines.append(f"共找到 {len(matched)} 个{type_name}")
        
        yield event.plain_result("\n".join(lines))


    @filter.command("voice.stats")
    async def voice_stats(self, event: AstrMessageEvent):
        voice_count = len(self.voice_map)
        video_count = len(self.video_map)
        
        lines = ["📊 媒体统计"]
        lines.append("-" * 30)
        lines.append(f"🎵 语音数量：{voice_count} 个")
        lines.append(f"🎬 视频数量：{video_count} 个")
        lines.append(f"📁 总计：{voice_count + video_count} 个")
        lines.append("-" * 30)
        lines.append(f"📂 语音目录：{self.voice_dir}")
        lines.append(f"📂 视频目录：{self.video_dir}")
        lines.append(f"📂 用户语音：{self.user_added_dir}")
        lines.append(f"📂 用户视频：{self.user_added_video_dir}")
        
        yield event.plain_result("\n".join(lines))
