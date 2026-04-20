from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.all import Context, Star, register
import os
import sys
import re
import logging

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from pixiv_engine import fetch_pixiv_image, translate_to_jp
except ImportError:
    def fetch_pixiv_image(*args, **kwargs):
        return [], "未找到图片"
    def translate_to_jp(keyword, proxy=None):
        return keyword

logger = logging.getLogger("AstrBot")

@register("pixiv_search", "Ruruka", "魔法少女的寻宝魔法", "1.4.9", "https://github.com/AstrBotDevs")
class PixivSearchSkill(Star):
    def __init__(self, context: Context, config: dict = None, **kwargs):
        super().__init__(context)
        self.config = config or {}

    def get_proxy(self):
        proxy_url = self.config.get("proxy", "http://192.168.65.254:7890")
        return {"http": proxy_url, "https": proxy_url}

    def get_cache_dir(self):
        return os.path.join(current_dir, "cache")

    @filter.regex(r"(?i)^(?:image|搜图)[:：\s]*(.*)")
    async def image_alias_regex(self, event: AstrMessageEvent):
        match = re.search(r"^(?:image|搜图)[:：\s]*(.*)", event.message_str, re.I)
        if match:
            keyword = match.group(1).strip()
            if not keyword:
                yield event.make_result().message("想要露露卡搜什么呢？格式是 image:关键词 哦")
                return
            translated = translate_to_jp(keyword, self.get_proxy())
            paths, used_tags = fetch_pixiv_image(translated, num=3, base_path=self.get_cache_dir(), proxy=self.get_proxy())
            if paths:
                result = event.make_result()
                pids = [os.path.basename(p).split("_")[0] for p in paths if "_" in os.path.basename(p)]
                pids_str = " (ID: " + ", ".join(pids) + ")" if pids else ""
                tag_info = f"感应成功！{pids_str}"
                result.message(tag_info)
                for p in paths:
                    if os.path.exists(p):
                        result.file_image(os.path.abspath(p))
                yield result
            else:
                yield event.make_result().message("未找到图片~")

    @filter.regex(r".*(?:来|搜|找)(?:几张|张|一下|下|点)(.+?)(?:标志|角色|的)(?:图|照片|壁纸|美图|印象图).*")
    async def search_image_regex_natural(self, event: AstrMessageEvent):
        msg_str = event.message_str
        match = re.search(r"(?:来|搜|找)(?:几张|张|一下|下|点)(.+?)(?:标志|角色|的)?(?:图|照片|壁纸|美图|印象图)", msg_str)
        if not match: return
        
        raw_keyword = match.group(1).strip()
        num = 3 if any(kw in msg_str for kw in ["几张", "点"]) else 1
        sender_name = "酱"
        if event.message_obj and event.message_obj.sender:
            sender_name = event.message_obj.sender.nickname or str(event.message_obj.sender.user_id)

        target_name = sender_name if raw_keyword in ["我", "咱", "自己", "俺", "我的"] else raw_keyword
        is_impression = "印象" in msg_str
        description = f"🔮 露露卡感应到了【{target_name}】的二次元气息..."
        search_tags = [target_name]

        if is_impression:
            try:
                from astrbot.api.provider import ProviderManager
                provider_mgr = ProviderManager.get_instance()
                llm_provider = provider_mgr.get_default_provider()
                if llm_provider:
                    history_text = ""
                    try:
                        history = await self.context.get_messages(event.message_obj.session_id, limit=15)
                        if history:
                            history_text = chr(10).join([f"{m.sender.nickname or m.sender.user_id}: {m.message_str}" for m in history if hasattr(m, "message_str") and m.message_str])
                    except: pass

                    prompt = f"你是一位捕捉灵魂色彩的感应者。用户【{target_name}】发起了“印象图”请求。{chr(10)}请根据其昵称和记录分析精神氛围，转化为3个日语标签。{chr(10)}---记录---{chr(10)}{history_text if history_text else '无'}{chr(10)}---规则---{chr(10)}1. 直接输出：描述：xxx{chr(10)}标签：tag1, tag2, tag3{chr(10)}2. 禁止Markdown。"
                    messages = [{"role": "user", "content": prompt}]
                    try:
                        response = await llm_provider.text_chat(messages, [])
                    except:
                        response = await llm_provider.text_chat(prompt, [])
                    
                    completion_text = ""
                    if hasattr(response, "completion_text"): completion_text = response.completion_text
                    elif hasattr(response, "text"): completion_text = response.text
                    else: completion_text = str(response)
                    
                    logger.info(f"[Pixiv感应] LLM响应: {completion_text}")
                    
                    desc_match = re.search(r'(?:描述|description)[:：]\s*(.*)', completion_text, re.I | re.M)
                    tags_match = re.search(r'(?:标签|tags)[:：]\s*(.*)', completion_text, re.I | re.M)
                    
                    if desc_match:
                        description = f"🔮 印象：{desc_match.group(1).strip()}"
                    if tags_match:
                        clean_tags = re.sub(r'[` "{}[\]$]+', '', tags_match.group(1)).strip()
                        search_tags = [t.strip() for t in re.split(r'[，、\s/|；,]', clean_tags) if t.strip()][:3]
            except Exception as e:
                logger.error(f"[Pixiv感应] LLM失败: {e}")

        translated_tags = [translate_to_jp(t, self.get_proxy()) for t in search_tags if t]
        paths = []
        attempts = []
        if len(translated_tags) >= 3:
            attempts = [" ".join(translated_tags[:3]), " ".join(translated_tags[:2]), translated_tags[0]]
        elif translated_tags:
            attempts = [" ".join(translated_tags), translated_tags[0]]

        for query in attempts:
            if not query: continue
            paths, _ = fetch_pixiv_image(query, num=num, base_path=self.get_cache_dir(), proxy=self.get_proxy())
            if paths:
                break

        if paths:
            result = event.make_result()
            pids = [os.path.basename(p).split("_")[0] for p in paths if "_" in os.path.basename(p)]
            pids_str = " (ID: " + ", ".join(pids) + ")" if pids else ""
            
            # 整合魔法气息报告
            tag_display = ", ".join(translated_tags) if translated_tags else "神秘残留"
            tag_info = f"{description}{pids_str}"
            
            result.message(tag_info)
            for p in paths:
                if os.path.exists(p): 
                    result.file_image(os.path.abspath(p))
            yield result
        else:
            yield event.make_result().message("唔... 露露卡已经很努力感应了，但没找到新鲜的图呢。")
