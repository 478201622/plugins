from __future__ import annotations
import re
import time
import random
import base64
import tempfile # 新增：用于创建临时文件
import os       # 新增：用于文件操作
from typing import Dict, List
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
# from astrbot.api.all import llm_tool # 统一使用 filter.llm_tool
from .core.api import ZhuaXiaBaApi
from .core.client import ZhuaXiaBaHttpClient
from .core.comment_store import CommentedThreadStore
from .core.config import ZhuaXiaBaPluginConfig
from .core.llm_action import ZhuaXiaBaLLMAction
from .core.service import ALLOWED_TAB_IDS, ZhuaXiaBaService
from .core.auto_trigger import AutoTriggerManager
from astrbot.api.message_components import Image


# 1x1 透明像素图片，用于绕开传话筒的文本转图片处理
_temp_img_data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=")
# 修改为创建临时文件，因为 file_image 不支持 data URI 协议
_temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
_temp_file.write(_temp_img_data)
_temp_file.close()
_TRANSPARENT_PIXEL = _temp_file.name


@register("zhuaxiaba", "落日七号", "面向抓虾吧使用场景的 AstrBot 插件", "1.0.0", "")
class ZhuaXiaBaPlugin(Star):
    def __init__(self, context: Context, config: dict = None, **kwargs):
        super().__init__(context)
        self.cfg = ZhuaXiaBaPluginConfig(config or {}, context)
        self.client = ZhuaXiaBaHttpClient(self.cfg)
        self.api = ZhuaXiaBaApi(self.client)
        self.service = ZhuaXiaBaService(self.api, self.cfg)
        self.llm = ZhuaXiaBaLLMAction(self.cfg)
        self.comment_store = CommentedThreadStore()
        self.auto_trigger = AutoTriggerManager(self.cfg)
        # 缓存推荐话题，等待用户确认（用于自动触发功能）
        self._pending_topics: Dict[str, Dict] = {}

    def _extract_author_from_thread(self, thread: dict) -> str:
        """从帖子数据中提取作者名。"""
        # 尝试从 author 对象获取
        author_obj = thread.get("author")
        if isinstance(author_obj, dict):
            name = (
                author_obj.get("name_show")
                or author_obj.get("user_name")
                or author_obj.get("nickname")
                or author_obj.get("name")
            )
            if name:
                return str(name)
        # 尝试直接字段
        name = (
            thread.get("author_name")
            or thread.get("user_name")
            or thread.get("nickname")
            or thread.get("name_show")
        )
        if name:
            return str(name)
        # 如果 author 是字符串
        if isinstance(author_obj, str) and author_obj:
            return author_obj
        return "匿名"

    async def terminate(self):
        await self.client.close()

    # ========== LLM 工具调用方法 ==========
    @filter.llm_tool(name="zhuaxiaba_smart_publish")
    async def zhuaxiaba_smart_publish(self, event: AstrMessageEvent, request: str) -> str:
        """ 
        根据用户请求智能生成标题和正文，然后发布到抓虾吧。
        Args:
            request (str): 发帖请求，例如"去抓虾吧发个帖子，聊聊小龙虾养殖技巧"
        Returns: 
            发帖结果 
        """
        result = await self._do_smart_publish_from_request(event, request)
        # 使用 event.plain_result 包装消息，避免使用 MessageChain
        return result

    @filter.llm_tool(name="zhuaxiaba_list_threads")
    async def zhuaxiaba_list_threads(self, event: AstrMessageEvent, sort_type: int = 0) -> str:
        """ 
        获取抓虾吧帖子列表。
        Args:
            sort_type (int): 排序类型，0=最新，1=热门
        Returns: 
            帖子列表 
        """
        return await self._do_list_threads(sort_type=sort_type)

    @filter.llm_tool(name="zhuaxiaba_reply_thread")
    async def zhuaxiaba_reply_thread(self, event: AstrMessageEvent, thread_id: str, content: str) -> str:
        """ 
        回复抓虾吧指定帖子。
        Args:
            thread_id (str): 帖子ID
            content (str): 回复内容
        Returns: 
            回复结果 
        """
        result = await self._do_reply_thread(thread_id, content)
        # 使用 event.plain_result 包装消息，避免使用 MessageChain
        return result

    @staticmethod
    def _parse_title_and_content(raw: str) -> tuple[str, str]:
        if not raw:
            raise RuntimeError("内容不能为空")
        if "|" not in raw:
            raise RuntimeError("请使用竖线分隔，例如：标题 | 内容")
        title, content = [part.strip() for part in raw.split("|", 1)]
        return title, content

    @staticmethod
    def _parse_publish_args(raw: str) -> tuple[str | None, str, str]:
        if not raw:
            raise RuntimeError("内容不能为空")
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) == 2:
            title, content = parts
            return None, title, content
        if len(parts) == 3:
            tab_id, title, content = parts
            return tab_id, title, content
        raise RuntimeError("请使用：标题 | 内容 或 板块ID | 标题 | 内容")

    @staticmethod
    def _build_tab_aliases() -> list[tuple[str, str]]:
        alias_map: dict[str, str] = {}
        for tab_id, tab_name in ALLOWED_TAB_IDS.items():
            normalized_id = str(tab_id)
            normalized_name = str(tab_name).strip()
            if normalized_name:
                alias_map[normalized_name] = normalized_id
                alias_map[f"{normalized_name}频道"] = normalized_id
                alias_map[f"{normalized_name}板块"] = normalized_id
        if normalized_id == "4738654":
            alias_map["酒馆"] = normalized_id
            alias_map["酒馆频道"] = normalized_id
        if normalized_id == "4666767":
            alias_map["摸鱼"] = normalized_id
            alias_map["摸鱼频道"] = normalized_id
        if normalized_id == "4666770":
            alias_map["乐园"] = normalized_id
            alias_map["乐园频道"] = normalized_id
        return sorted(alias_map.items(), key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def _extract_tab_id_from_request(cls, raw: str) -> tuple[str | None, str]:
        text = (raw or "").strip()
        if not text:
            return None, ""

        match = re.search(r"\b(0|4666758|4666765|4666767|4666770|4743771|4738654|4738660)\b", text)
        if match:
            tab_id = match.group(1)
            cleaned = (text[: match.start()] + " " + text[match.end() :]).strip()
            return tab_id, re.sub(r"\s+", " ", cleaned).strip(" ，,。")

        cleaned = text
        resolved_tab_id = None
        for alias, candidate_tab_id in cls._build_tab_aliases():
            if alias and alias in cleaned:
                resolved_tab_id = candidate_tab_id
                cleaned = cleaned.replace(alias, " ")
                break
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")
        return resolved_tab_id, cleaned

    @staticmethod
    def _extract_topic_from_request(raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return ""

        patterns = [
            r"(?:主题是|主题聊|主题聊聊|聊聊|讨论一下|讨论|说说|想聊聊|想讨论|发个帖子聊聊|发帖聊聊|发个帖子说说|发帖说说)\s*[:：,，]?\s*(.+)$",
            r"(?:发个帖子|发一帖|发帖|写个帖子|写一帖|写帖)\s*[:：,，]?\s*(.+)$",
            r"关于\s*(.+?)\s*(?:发个帖子|发一帖|发帖|聊聊|讨论一下|讨论)?$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                topic = match.group(1).strip(" ，,。！？!?；;:：")
                if topic:
                    return topic

        cleaned = text
        cleanup_patterns = [
            r"去?抓虾吧",
            r"到抓虾吧",
            r"在抓虾吧",
            r"帮我",
            r"麻烦",
            r"直接",
            r"给我",
            r"想",
            r"请",
            r"发个帖子",
            r"发一帖",
            r"发帖",
            r"写个帖子",
            r"写一帖",
            r"写帖",
            r"频道",
            r"板块",
        ]
        for pattern in cleanup_patterns:
            cleaned = re.sub(pattern, " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。！？!?；;:：")
        return cleaned

    @classmethod
    def _parse_smart_publish_request(cls, raw: str) -> tuple[str | None, str]:
        tab_id, remaining = cls._extract_tab_id_from_request(raw)
        topic = cls._extract_topic_from_request(remaining)
        if not topic:
            raise RuntimeError("未能从请求中识别发帖主题，请明确说明想聊什么")
        return tab_id, topic

    @staticmethod
    def _strip_command_prefix(raw: str, *prefixes: str) -> str:
        text = (raw or "").strip()
        for prefix in prefixes:
            prefix = prefix.strip()
            if text.startswith(prefix):
                return text[len(prefix):].strip()
            if text.startswith("/" + prefix):
                return text[len(prefix) + 1 :].strip()
        return text

    @staticmethod
    def _parse_smart_publish_args(raw: str) -> tuple[str | None, str]:
        text = (raw or "").strip()
        if not text:
            return None, "分享一个最近的想法或经历"
        if "|" not in text:
            return None, text
        tab_id, topic = [part.strip() for part in text.split("|", 1)]
        return (tab_id or None), (topic or "分享一个最近的想法或经历")

    async def _do_smart_publish_from_request(self, event, request: str) -> str:
        tab_id, topic = self._parse_smart_publish_request(request)
        return await self._do_smart_publish_thread(event, topic, tab_id=tab_id)

    @staticmethod
    def _render_thread_list(items: list[dict]) -> str:
        if not items:
            return "未获取到帖子列表"
        lines = ["帖子列表："]
        for item in items:
            lines.append(
                f"{item['index']}. [{item.get('thread_id', '-')}] {item['title']}\n"
                f"作者：{item['author']}\n"
                f"摘要：{item['snippet']}\n"
                f"链接：{item['url']}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _render_replyme(items: list[dict]) -> str:
        if not items:
            return "暂无回复我的消息"
        lines = ["回复我的消息："]
        for item in items:
            unread_mark = "未读" if str(item.get("unread")) == "1" else "已读"
            lines.append(
                f"{item['index']}. [{unread_mark}] {item['username']}\n"
                f"评论：{item['content']}\n"
                f"引用：{item['quote_content']}\n"
                f"thread_id={item.get('thread_id')} post_id={item.get('post_id')}\n"
                f"链接：{item.get('url', '')}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _parse_batch_count(raw: str) -> int:
        text = (raw or "").strip()
        if not text:
            raise RuntimeError("用法：抓虾吧一键评论 1~10")
        try:
            count = int(text)
        except ValueError as exc:
            raise RuntimeError("评论数量必须是 1~10 的整数") from exc
        if not 1 <= count <= 10:
            raise RuntimeError("评论数量必须在 1~10 之间")
        return count

    async def _do_publish_thread(self, title: str, content: str, tab_id: str | None = None) -> str:
        result = await self.service.publish_thread(title=title, content=content, tab_id=tab_id)
        return f"🦐 已在抓虾吧发帖成功\n📌 标题：{title}\n📝 正文：{content}\n🔗 链接：{result['url']}"

    async def _do_list_threads(self, sort_type: int = 0) -> str:
        items = await self.service.list_threads(sort_type=sort_type)
        return self._render_thread_list(items)

    async def _do_view_thread(self, thread_id: str) -> str:
        detail = await self.service.get_thread_detail(thread_id=thread_id)
        lines = [
            f"标题：{detail['title']}",
            f"链接：{detail['url']}",
            "",
            "主贴正文：",
            detail.get("content") or "（暂无正文）",
            "",
            "楼层：",
        ]
        posts = detail.get("posts", [])
        if not posts:
            lines.append("未解析到楼层内容")
        else:
            for idx, post in enumerate(posts, start=1):
                lines.append(
                    f"{idx}. post_id={post.get('post_id')} 作者：{post.get('author')}\n{post.get('content')}"
                )
        return "\n\n".join(lines)

    async def _do_reply_thread(self, thread_id: str, content: str) -> str:
        result = await self.service.reply_thread(thread_id=thread_id, content=content)
        return f"🦐 已在抓虾吧评论成功\n📝 本楼层内容：{content}\n🔗 链接：{result['url']}"

    async def _do_reply_post(self, post_id: str, content: str) -> str:
        result = await self.service.reply_post(post_id=post_id, content=content)
        url = result.get("url") or f"post_id={result['post_id']}"
        return f"🦐 已在抓虾吧回复楼层成功\n📝 本楼层内容：{content}\n🔗 链接：{url}"

    async def _do_like_thread(self, thread_id: str) -> str:
        result = await self.service.like_thread(thread_id=thread_id)
        return f"🦐 已在抓虾吧{result['action']}成功\n🔗 链接：{result['url']}"

    async def _do_like_post(self, thread_id: str, post_id: str) -> str:
        result = await self.service.like_post(thread_id=thread_id, post_id=post_id)
        return f"🦐 已在抓虾吧{result['action']}成功\n🔗 链接：{result['url']}"

    async def _do_replyme(self, pn: int = 1) -> str:
        items = await self.service.list_replyme(pn=pn)
        return self._render_replyme(items)

    async def _do_smart_publish_thread(self, event, topic: str, tab_id: str | None = None) -> str:
        title, content = await self.llm.generate_thread(event, topic)
        result = await self.service.publish_thread(title=title, content=content, tab_id=tab_id)
        return f"🦐 已在抓虾吧智能发帖成功\n💡 主题：{topic}\n📌 标题：{title}\n📝 正文：{content}\n🔗 链接：{result['url']}"

    async def _do_smart_reply_thread(self, event, thread_id: str, guidance: str | None = None) -> str:
        detail = await self.service.get_thread_detail(thread_id=thread_id)
        main_post = detail.get("main_post") or {}
        main_post_content = main_post.get("content") or detail.get("content") or "（暂无正文）"
        main_post_author = main_post.get("author") or "楼主"
        target_text = (
            f"标题：{detail['title']}\n\n"
            f"主贴作者：{main_post_author}\n"
            f"主贴正文：\n{main_post_content}"
        )
        posts = detail.get("posts", [])
        if posts:
            target_text += "\n\n评论区上下文：\n" + "\n".join(
                f"作者：{post.get('author')} 内容：{post.get('content')}"
                for post in posts[:3]
            )
        content = await self.llm.generate_reply(event, target_text, mode="主贴", guidance=guidance)
        result = await self.service.reply_thread(thread_id=thread_id, content=content)
        return f"🦐 已在抓虾吧智能评论成功\n📌 帖子：{detail['title']}\n📝 本楼层内容：{content}\n🔗 链接：{result['url']}"

    async def _do_batch_smart_reply_threads(self, event, count: int) -> str:
        marked = self.comment_store.load()
        skipped = 0
        scanned = 0
        failures = 0
        successes: list[dict[str, str]] = []
        page = 1
        while len(successes) < count:
            items = await self.service.list_threads_page(sort_type=0, pn=page)
            if not items:
                break
            for item in items:
                thread_id = item.get("thread_id")
                if not thread_id:
                    continue
                scanned += 1
                thread_key = str(thread_id)
                if thread_key in marked:
                    skipped += 1
                    continue
                title = str(item.get("title") or "（无标题）")
                try:
                    detail = await self.service.get_thread_detail(thread_id=thread_key)
                    main_post = detail.get("main_post") or {}
                    main_post_content = main_post.get("content") or detail.get("content") or "（暂无正文）"
                    main_post_author = main_post.get("author") or "楼主"
                    target_text = (
                        f"标题：{detail['title']}\n\n"
                        f"主贴作者：{main_post_author}\n"
                        f"主贴正文：\n{main_post_content}"
                    )
                    posts = detail.get("posts", [])
                    if posts:
                        target_text += "\n\n评论区上下文：\n" + "\n".join(
                            f"作者：{post.get('author')} 内容：{post.get('content')}"
                            for post in posts[:3]
                        )
                    content = await self.llm.generate_reply(event, target_text, mode="主贴", guidance=None)
                    result = await self.service.reply_thread(thread_id=thread_key, content=content)
                    self.comment_store.mark(thread_key, title)
                except Exception as exc:
                    failures += 1
                    logger.error(f"[ZhuaXiaBaPlugin] 一键评论跳过 thread_id={thread_key}: {exc}")
                    continue
                marked[thread_key] = {"title": title}
                successes.append(
                    {
                        "thread_id": thread_key,
                        "title": title,
                        "content": content,
                        "url": result["url"],
                    }
                )
                if len(successes) >= count:
                    break
            page += 1

        lines = [
            f"🦐 抓虾吧一键评论完成",
            f"📊 目标 {count} 条，成功 {len(successes)} 条，跳过 {skipped} 条，失败 {failures} 条",
        ]
        if successes:
            lines.append("")
            lines.append("📋 本次已评论：")
            for idx, item in enumerate(successes, start=1):
                lines.append(
                    f"{idx}. [{item['thread_id']}] {item['title']}\n"
                    f" 📝 本楼层内容：{item['content']}\n"
                    f" 🔗 链接：{item['url']}"
                )
        if len(successes) < count:
            lines.append("")
            lines.append("未能凑满目标数量：没有更多未评论帖子可处理，或部分帖子在生成/发送评论时失败。")
        return "\n\n".join(lines)

    async def _do_smart_reply_post(self, event, thread_id: str, post_id: str, guidance: str | None = None) -> str:
        detail = await self.service.get_thread_detail(thread_id=thread_id)
        matched = None
        for post in detail.get("posts", []):
            if str(post.get("post_id")) == str(post_id):
                matched = post
                break
        if not matched:
            raise RuntimeError("未在帖子详情中找到对应楼层，请先确认 post_id 是否正确")
        target_text = f"楼层作者：{matched.get('author')}\n楼层内容：{matched.get('content')}"
        content = await self.llm.generate_reply(event, target_text, mode="楼层", guidance=guidance)
        result = await self.service.reply_post(post_id=post_id, content=content)
        url = result.get("url") or f"post_id={result['post_id']}"
        return f"🦐 已在抓虾吧智能回复楼层成功\n📌 帖子：{detail['title']}\n💬 回复楼层：{matched.get('author')} - {matched.get('content')[:50]}...\n📝 本楼层内容：{content}\n🔗 链接：{url}"

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧发帖", alias={"发抓虾吧"})
    async def publish_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧发帖", "发抓虾吧")
        if not raw:
            yield event.plain_result("用法：抓虾吧发帖 标题 | 内容 或 抓虾吧发帖 板块ID | 标题 | 内容")
            return
        try:
            tab_id, title, content = self._parse_publish_args(raw)
            yield event.plain_result(await self._do_publish_thread(title, content, tab_id=tab_id))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 发帖失败: {exc}")
            yield event.plain_result(f"发帖失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧智能发帖", alias={"抓虾吧写帖"})
    async def smart_publish_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧智能发帖", "抓虾吧写帖")
        tab_id, topic = self._parse_smart_publish_args(raw)
        try:
            yield event.plain_result(await self._do_smart_publish_thread(event, topic, tab_id=tab_id))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 智能发帖失败: {exc}")
            yield event.plain_result(f"智能发帖失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧列表", alias={"逛抓虾吧"})
    async def list_threads(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧列表", "逛抓虾吧")
        sort_type = 3 if raw in {"热门", "hot", "3"} else 0
        try:
            yield event.plain_result(await self._do_list_threads(sort_type=sort_type))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 获取帖子列表失败: {exc}")
            yield event.plain_result(f"获取帖子列表失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧看帖", alias={"看抓虾吧"})
    async def view_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧看帖", "看抓虾吧")
        if not raw:
            yield event.plain_result("用法：抓虾吧看帖 thread_id")
            return
        try:
            yield event.plain_result(await self._do_view_thread(raw))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 查看帖子失败: {exc}")
            yield event.plain_result(f"查看帖子失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧评论主贴", alias={"评论抓虾吧"})
    async def reply_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧评论主贴", "评论抓虾吧")
        if not raw or "|" not in raw:
            yield event.plain_result("用法：抓虾吧评论主贴 thread_id | 内容")
            return
        thread_id, content = [part.strip() for part in raw.split("|", 1)]
        try:
            yield event.plain_result(await self._do_reply_thread(thread_id, content))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 评论主贴失败: {exc}")
            yield event.plain_result(f"评论主贴失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧智能评论主贴", alias={"抓虾吧智能评论"})
    async def smart_reply_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧智能评论主贴", "抓虾吧智能评论")
        if not raw:
            yield event.plain_result("用法：抓虾吧智能评论主贴 thread_id [| 评论方向]")
            return
        thread_id, guidance = [part.strip() for part in raw.split("|", 1)] if "|" in raw else (raw.strip(), "")
        if not thread_id:
            yield event.plain_result("用法：抓虾吧智能评论主贴 thread_id [| 评论方向]")
            return
        try:
            yield event.plain_result(await self._do_smart_reply_thread(event, thread_id, guidance or None))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 智能评论主贴失败: {exc}")
            yield event.plain_result(f"智能评论主贴失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧一键评论")
    async def batch_smart_reply_threads(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧一键评论")
        try:
            count = self._parse_batch_count(raw)
            yield event.plain_result(await self._do_batch_smart_reply_threads(event, count))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 一键评论失败: {exc}")
            yield event.plain_result(f"一键评论失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧评论楼层", alias={"回复抓虾吧楼层"})
    async def reply_post(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧评论楼层", "回复抓虾吧楼层")
        if not raw or "|" not in raw:
            yield event.plain_result("用法：抓虾吧评论楼层 post_id | 内容")
            return
        post_id, content = [part.strip() for part in raw.split("|", 1)]
        try:
            yield event.plain_result(await self._do_reply_post(post_id, content))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 回复楼层失败: {exc}")
            yield event.plain_result(f"回复楼层失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧智能评论楼层")
    async def smart_reply_post(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧智能评论楼层")
        command_part, guidance = [part.strip() for part in raw.split("|", 1)] if "|" in raw else (raw.strip(), "")
        parts = command_part.split()
        if len(parts) < 2:
            yield event.plain_result("用法：抓虾吧智能评论楼层 thread_id post_id [| 评论方向]")
            return
        thread_id, post_id = parts[0], parts[1]
        try:
            yield event.plain_result(await self._do_smart_reply_post(event, thread_id, post_id, guidance or None))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 智能评论楼层失败: {exc}")
            yield event.plain_result(f"智能评论楼层失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧点赞主贴")
    async def like_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧点赞主贴")
        if not raw:
            yield event.plain_result("用法：抓虾吧点赞主贴 thread_id")
            return
        try:
            yield event.plain_result(await self._do_like_thread(raw))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 点赞主贴失败: {exc}")
            yield event.plain_result(f"点赞主贴失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧点赞楼层")
    async def like_post(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧点赞楼层")
        parts = raw.split()
        if len(parts) < 2:
            yield event.plain_result("用法：抓虾吧点赞楼层 thread_id post_id")
            return
        thread_id, post_id = parts[0], parts[1]
        try:
            yield event.plain_result(await self._do_like_post(thread_id, post_id))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 点赞楼层失败: {exc}")
            yield event.plain_result(f"点赞楼层失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧未读", alias={"抓虾吧消息"})
    async def replyme(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧未读", "抓虾吧消息")
        try:
            pn = int(raw) if raw else 1
        except ValueError:
            pn = 1
        try:
            yield event.plain_result(await self._do_replyme(pn=pn))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 获取未读回复失败: {exc}")
            yield event.plain_result(f"获取未读回复失败：{exc}")

    @filter.llm_tool(name="zhuaxiaba_publish_thread")
    async def llm_publish_thread_tool(
        self,
        event: AstrMessageEvent,
        title: str,
        content: str,
        tab_id: str = "",
    ):
        """
        发布一条抓虾吧主贴。
        Args:
            title(string): 帖子标题，最多30个字符
            content(string): 帖子正文，纯文本，最多1000个字符
            tab_id(string): 可选的板块 ID，留空则使用默认板块
        """
        try:
            result = await self._do_publish_thread(title, content, tab_id.strip() or None)
            res = event.make_result()
            res.message(result)
            # 如果 _do_publish_thread 返回了图片 URL，可以在这里添加
            # res.file_image(image_url)
            yield res
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 发帖失败: {exc}")
            error_msg = f"发帖失败：{exc}"
            res = event.make_result()
            res.message(error_msg)
            yield res

    @filter.llm_tool(name="zhuaxiaba_smart_publish_thread")
    async def llm_smart_publish_thread_tool(
        self,
        event: AstrMessageEvent,
        topic: str = "",
        tab_id: str = "",
    ):
        """
        围绕一个明确主题智能生成标题和正文，然后发布到抓虾吧。
        Args:
            topic(string): 发帖主题，例如"天气对心情的影响"
            tab_id(string): 可选的板块 ID，留空则使用默认板块
        """
        normalized_topic = str(topic or "").strip()
        normalized_tab_id = tab_id.strip() or None
        raw_message = str(getattr(event, "message_str", "") or "").strip()
        if not normalized_topic and raw_message:
            try:
                parsed_tab_id, parsed_topic = self._parse_smart_publish_request(raw_message)
                normalized_topic = parsed_topic
                normalized_tab_id = normalized_tab_id or parsed_tab_id
            except Exception:
                pass
        if not normalized_topic:
            error_msg = "智能发帖失败：缺少 topic 参数，请提供明确的发帖主题"
            res = event.make_result()
            res.message(error_msg)
            yield res
            return
        try:
            result = await self._do_smart_publish_thread(event, normalized_topic, normalized_tab_id)
            res = event.make_result()
            res.message(result)
            # 如果 _do_smart_publish_thread 返回了图片 URL，可以在这里添加
            # res.file_image(image_url)
            yield res
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 智能发帖失败: {exc}")
            error_msg = f"智能发帖失败：{exc}"
            res = event.make_result()
            res.message(error_msg)
            yield res

    @filter.llm_tool(name="zhuaxiaba_smart_publish_from_request")
    async def llm_smart_publish_from_request_tool(self, event: AstrMessageEvent, request: str = ""):
        """
        直接接收自然语言发帖请求，由插件内部识别板块和主题后再智能发帖。
        Args:
            request(string): 原始自然语言请求，例如"去抓虾吧赛博酒馆发个帖子，聊聊天气对心情的影响"
        """
        normalized_request = str(request or "").strip()
        if not normalized_request:
            normalized_request = str(getattr(event, "message_str", "") or "").strip()
        if not normalized_request:
            return "智能发帖失败：缺少 request 参数，请直接提供原始发帖请求"
        try:
            result = await self._do_smart_publish_from_request(event, normalized_request)
            # 使用 event.plain_result 包装消息，避免使用 MessageChain
            return result
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 自然语言智能发帖失败: {exc}")
            return f"智能发帖失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_list_threads")
    async def llm_list_threads_tool(self, event: AstrMessageEvent, sort_type: str = "时间"):
        """
        获取抓虾吧帖子列表。
        
        Args:
            sort_type (str): 排序方式，"时间"=最新回复，"热门"=热门帖子
            
        Returns:
            帖子列表，包含帖子ID、标题、作者、回复数等信息
        """
        try:
            normalized = str(sort_type or "时间").strip()
            sort = 3 if normalized in {"热门", "hot", "3"} else 0
            result = await self._do_list_threads(sort_type=sort)
            # 使用 event.plain_result 包装消息，避免使用 MessageChain
            return result
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 获取帖子列表失败: {exc}")
            return f"获取帖子列表失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_view_thread")
    async def llm_view_thread_tool(self, event: AstrMessageEvent, thread_id: str):
        """
        查看抓虾吧指定帖子的详细内容。
        
        Args:
            thread_id (str): 帖子ID
            
        Returns:
            帖子详情，包含标题、作者、正文、评论列表等信息
        """
        try:
            result = await self._do_view_thread(thread_id)
            # 使用 event.plain_result 包装消息，避免使用 MessageChain
            return result
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 查看帖子失败: {exc}")
            return f"查看帖子失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_reply_thread")
    async def llm_reply_thread_tool(self, event: AstrMessageEvent, thread_id: str, content: str):
        """
        回复抓虾吧指定主贴。
        
        Args:
            thread_id (str): 帖子ID
            content (str): 回复内容
            
        Returns:
            回复结果
        """
        try:
            result = await self._do_reply_thread(thread_id, content)
            # 使用 event.plain_result 包装消息，避免使用 MessageChain
            return result
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 评论主贴失败: {exc}")
            return f"评论主贴失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_smart_reply_thread")
    async def llm_smart_reply_thread_tool(
        self,
        event: AstrMessageEvent,
        thread_id: str,
        guidance: str = "",
    ):
        """
        智能回复抓虾吧主贴。
        使用 LLM 根据帖子标题、正文和现有评论自动生成合适的回复。
        
        Args:
            thread_id (str): 帖子ID
            guidance (str, optional): 额外的评论方向指导，例如"表示赞同"、"提出疑问"、"分享经验"、"幽默回应"等
            
        Returns:
            智能回复结果，包含生成的回复内容和链接
        """
        try:
            result = await self._do_smart_reply_thread(event, thread_id, guidance.strip() or None)
            # 使用 event.plain_result 包装消息，避免使用 MessageChain
            return result
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 智能评论主贴失败: {exc}")
            return f"智能评论主贴失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_reply_post")
    async def llm_reply_post_tool(self, event: AstrMessageEvent, post_id: str, content: str):
        """
        回复抓虾吧指定楼层（评论）。
        
        Args:
            post_id (str): 楼层ID
            content (str): 回复内容
            
        Returns:
            回复结果
        """
        try:
            result = await self._do_reply_post(post_id, content)
            # 使用 event.plain_result 包装消息，避免使用 MessageChain
            return result
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 回复楼层失败: {exc}")
            return f"回复楼层失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_smart_reply_post")
    async def llm_smart_reply_post_tool(
        self,
        event: AstrMessageEvent,
        thread_id: str,
        post_id: str,
        guidance: str = "",
    ):
        """
        智能回复抓虾吧指定楼层（评论）。
        使用 LLM 根据楼层内容自动生成合适的回复。
        
        Args:
            thread_id (str): 帖子ID
            post_id (str): 楼层ID
            guidance (str, optional): 额外的评论方向指导，例如"表示赞同"、"提出疑问"、"补充观点"等
            
        Returns:
            智能回复结果，包含生成的回复内容和链接
        """
        try:
            result = await self._do_smart_reply_post(event, thread_id, post_id, guidance.strip() or None)
            # 使用 event.plain_result 包装消息，避免使用 MessageChain
            return result
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 智能评论楼层失败: {exc}")
            return f"智能评论楼层失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_like_thread")
    async def llm_like_thread_tool(self, event: AstrMessageEvent, thread_id: str):
        """
        点赞抓虾吧指定主贴。
        
        Args:
            thread_id (str): 帖子ID
            
        Returns:
            点赞结果
        """
        try:
            result = await self._do_like_thread(thread_id)
            # 使用 event.plain_result 包装消息，避免使用 MessageChain
            return result
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 点赞主贴失败: {exc}")
            return f"点赞主贴失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_like_post")
    async def llm_like_post_tool(self, event: AstrMessageEvent, thread_id: str, post_id: str):
        """
        点赞抓虾吧指定楼层（评论）。
        
        Args:
            thread_id (str): 帖子ID
            post_id (str): 楼层ID
            
        Returns:
            点赞结果
        """
        try:
            result = await self._do_like_post(thread_id, post_id)
            # 使用 event.plain_result 包装消息，避免使用 MessageChain
            return result
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 点赞楼层失败: {exc}")
            return f"点赞楼层失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_replyme")
    async def llm_replyme_tool(self, event: AstrMessageEvent, pn: int = 1):
        """
        获取抓虾吧回复我的消息列表。
        
        Args:
            pn (int): 页码，默认为1
            
        Returns:
            回复消息列表
        """
        try:
            result = await self._do_replyme(pn=pn)
            # 使用 event.plain_result 包装消息，避免 using MessageChain
            return result
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 获取回复消息失败: {exc}")
            return f"获取回复消息失败：{exc}"

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧帮助", alias={"抓虾吧help"})
    async def show_help(self, event):
        help_text = (
            "抓虾吧接口 - 使用帮助\n\n"
            "先在插件设置中填写 TB_TOKEN。\n"
            "可选配置：LLM 模型 ID、人格 ID、智能发帖/评论预设词、自动触发设置。\n\n"
            "【自动触发功能】\n"
            "当聊天中提到抓虾吧/龙虾等关键词时，会自动分享有趣话题\n"
            "• 抓虾吧自动触发 [on/off] - 开关自动触发\n"
            "• 自动触发后，回复数字 1-5 可查看对应帖子详情\n\n"
            "【命令列表】\n"
            "1. 抓虾吧发帖 标题 | 内容\n"
            "   或：抓虾吧发帖 板块ID | 标题 | 内容\n"
            "2. 抓虾吧智能发帖 主题\n"
            "   或：抓虾吧智能发帖 板块ID | 主题\n"
            "   LLM 工具支持：zhuaxiaba_smart_publish_thread(topic, tab_id)\n"
            "   自然语言工具支持：zhuaxiaba_smart_publish_from_request(request)\n"
            "3. 抓虾吧列表 [时间|热门]\n"
            "4. 抓虾吧看帖 thread_id\n"
            "5. 抓虾吧评论主贴 thread_id | 内容\n"
            "6. 抓虾吧智能评论主贴 thread_id [| 评论方向]\n"
            "7. 抓虾吧一键评论 1~10\n"
            "8. 抓虾吧评论楼层 post_id | 内容\n"
            "9. 抓虾吧智能评论楼层 thread_id post_id [| 评论方向]\n"
            "10. 抓虾吧点赞主贴 thread_id\n"
            "11. 抓虾吧点赞楼层 thread_id post_id\n"
            "12. 抓虾吧未读 [页码]"
        )
        yield event.plain_result(help_text)

    # ==================== 自动触发监听 ====================
    

    async def _fetch_related_topics(self, keyword: str, limit: int = 5) -> List[Dict]:
        """
        从抓虾吧获取与关键词相关的话题（只读）
        
        Args:
            keyword: 关键词
            limit: 获取数量
            
        Returns:
            话题列表
        """
        logger.info(f'[ZhuaXiaBaPlugin] 开始抓取关键字: {keyword}')
        
        try:
            # 获取帖子列表
            threads = await self.api.get_threads(sort_type=0, pn=1)
            
            if not threads or 'thread_list' not in threads:
                pass
                return []
            
            # 筛选相关话题（简单匹配标题）
            related = []
            keyword_lower = keyword.lower()
            
            for thread in threads['thread_list']:
                title = thread.get("title", "")
                content_text = thread.get("content", "")
                
                # 匹配关键词
                if any(kw in title or kw in content_text for kw in ["虾", "龙虾", "抓虾", "养虾"]):
                    related.append({
                        "id": thread.get("id"),
                        "title": title,
                        "content": content_text[:100] + "..." if len(content_text) > 100 else content_text,
                        "author": self._extract_author_from_thread(thread),
                        "reply_count": thread.get("reply_count", 0)
                    })
                
                if len(related) >= limit:
                    break
            
            logger.info(f'[ZhuaXiaBaPlugin] 抓取完成，共 {len(related)} 个结果')
            return related
            
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 获取相关话题失败: {exc}")
            return []

    @filter.regex(r".*(?:龙虾|抓虾|养虾|小龙虾).*", priority=200, block=False)
    async def auto_trigger_listener(self, event: AstrMessageEvent):
        """
        自动触发监听：检测到关键词后，搜索相关帖子并推荐给群友
        二阶段模型第一阶段：提取 → 推荐（等待用户确认，不自动执行）
        """
        session_id = event.session_id
        message = event.message_str or ""
        
        # 检查是否应该触发（关键词匹配 + 冷却时间）
        if not self.auto_trigger.should_trigger(message, session_id):
            return
        # 记录触发时间
        self.auto_trigger.record_trigger(session_id)
        
        logger.info(f'[ZhuaXiaBaPlugin] 自动触发: 检测到关键词，开始搜索相关帖子')
        
        try:
            # 从抓虾吧获取帖子列表
            raw_res = await self.api.get_threads(sort_type=0, pn=1)
            threads = raw_res.get('data', {}).get('thread_list', [])
            
            if not threads:
                logger.info('[ZhuaXiaBaPlugin] 自动触发: 未获取到帖子列表')
                return # 直接取最新的热门帖子（不筛选关键词，展示抓虾吧最新动态）
            selected_threads = []
            for thread in threads[:5]: # 取前5个最新帖子
                title = thread.get("title", "")
                content = thread.get("first_floor", {}).get("content", "") if isinstance(thread.get("first_floor"), dict) else ""
                
                selected_threads.append({
                    "thread_id": thread.get("id"),
                    "title": title or "无标题",
                    "author": self._extract_author_from_thread(thread),
                    "reply_count": thread.get("reply_num", 0),
                    "snippet": content[:80] + "..." if len(content) > 80 else content
                })
            
            related_threads = selected_threads
            
            if not related_threads:
                logger.info('[ZhuaXiaBaPlugin] 自动触发: 未找到相关帖子')
                return # 保存到待处理缓存，等待用户确认
            self._pending_topics[session_id] = {
                "timestamp": __import__('time').time(),
                "threads": related_threads
            }
            
            # 构建推荐消息
            lines = ["🦐 说到抓虾吧，我去看了一眼，发现这些有趣的帖子：", ""]
            
            for idx, thread in enumerate(related_threads, 1):
                lines.append(f"{idx}. {thread['title']}")
                lines.append(f"   👤 {thread['author']} | 💬 {thread['reply_count']}回复")
                if thread['snippet']:
                    lines.append(f"   📝 {thread['snippet']}")
                lines.append("")
            
            lines.append("─────────────────────")
            lines.append("💡 快捷操作：")
            lines.append("   • 回复数字 1-5 查看对应帖子详情")
            lines.append("   • 回复「去发帖」或「发第1个帖子」让我帮你发帖")
            lines.append("⏰ 推荐有效期5分钟，过期后需要重新触发关键词~")
            
            result_text = chr(10).join(lines)
            
            logger.info(f'[ZhuaXiaBaPlugin] 自动触发: 已向群友推荐 {len(related_threads)} 个话题')
            res = event.make_result()
            res.message(result_text)
            res.file_image(_TRANSPARENT_PIXEL) # 使用 base64 图片
            yield res
            
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 自动触发失败: {exc}")
            # 静默失败，不影响群聊体验
    


    async def _generate_interesting_topic(self, event, context_message: str) -> str:
        """
        根据聊天上下文生成有趣的话题
        """
        persona_prompt = await self.llm._get_persona_prompt()
        task_prompt = (
            f"{self.cfg.auto_share_topic_prompt}\n\n"
            "任务：根据当前聊天内容，生成一个有趣、轻松、适合大家讨论的话题。\n"
            "要求：\n"
            "1. 话题要贴近生活、有共鸣点\n"
            "2. 能引发互动和讨论\n"
            "3. 语气自然、像真实吧友\n"
            "4. 只输出话题主题，不要解释\n"
            "5. 话题长度控制在20字以内"
        )
        
        system_prompt = self.llm._merge_system_prompt(persona_prompt, task_prompt)
        
        prompt = f"当前聊天内容：{context_message}\n\n请根据以上内容生成一个有趣的话题主题："
        
        result = self.llm._clean_text(await self.llm._generate_text(event, prompt=prompt, system_prompt=system_prompt))
        
        if not result:
            # 如果生成失败，使用默认话题
            return "大家最近有什么有趣的经历分享吗？"
        
        return result[:50]  # 限制长度
    
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧自动触发", alias={"抓虾吧自动", "抓虾吧auto"})
    async def toggle_auto_trigger(self, event):
        """
        切换自动触发功能的开关状态
        """
        raw = event.message_str or ""
        # 提取参数
        parts = raw.split()
        if len(parts) >= 2:
            arg = parts[1].lower()
            if arg in ("on", "开", "启用", "true", "1"):
                self.cfg._cfg["auto_trigger_enabled"] = True
                self.cfg.save_config()
                yield event.plain_result("✅ 抓虾吧自动触发已开启")
                return
            elif arg in ("off", "关", "禁用", "false", "0"):
                self.cfg._cfg["auto_trigger_enabled"] = False
                self.cfg.save_config()
                yield event.plain_result("❌ 抓虾吧自动触发已关闭")
                return
        # 显示当前状态
        status = "开启" if self.cfg.auto_trigger_enabled else "关闭"
        yield event.plain_result(
            f"抓虾吧自动触发当前状态：{status}\n"
            f"触发关键词：{', '.join(self.cfg.auto_trigger_keywords)}\n"
            f"冷却时间：{self.cfg.auto_trigger_cooldown}分钟\n\n"
            f"用法：抓虾吧自动触发 [on/off/开/关]"
        )


    # ==================== 数字回复查看帖子详情 ====================
    
    @filter.regex(r"^[1-5]$", priority=998, block=False)
    async def on_number_reply(self, event: AstrMessageEvent):
        """
        监听数字回复（1-5）：当用户回复数字时，查看对应序号的帖子详情
        这是自动触发功能的第二阶段：执行（查看详情）
        """
        session_id = event.session_id
        message = (event.message_str or "").strip()
        
        # 检查是否有待处理的帖子推荐
        if session_id not in self._pending_topics:
            return
        pending_data = self._pending_topics[session_id]
        
        # 检查是否过期（5分钟）
        import time
        if time.time() - pending_data.get("timestamp", 0) > 300:
            del self._pending_topics[session_id]
            return
        # 解析数字
        try:
            index = int(message)
        except ValueError:
            return
        threads = pending_data.get("threads", [])
        if not threads or index < 1 or index > len(threads):
            return
        # 获取对应帖子
        selected_thread = threads[index - 1]
        thread_id = selected_thread.get("thread_id")
        
        if not thread_id:
            res = event.make_result()
            res.message("❌ 无法获取帖子ID，请稍后再试")
            res.file_image(_TRANSPARENT_PIXEL) # 使用 base64 图片
            yield res
            return
        logger.info(f'[ZhuaXiaBaPlugin] 用户选择查看帖子 {index}: thread_id={thread_id}')
        
        try:
            # 查看帖子详情
            detail = await self._do_view_thread(str(thread_id))
            
            # 清除待处理状态（可选：保留以允许连续查看）
            # del self._pending_topics[session_id]
            
            res = event.make_result()
            res.message(detail)
            res.file_image(_TRANSPARENT_PIXEL) # 使用 base64 图片
            yield res
            
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 查看帖子详情失败: {exc}")
            res = event.make_result()
            res.message(f"❌ 查看帖子详情失败：{exc}")
            res.file_image(_TRANSPARENT_PIXEL) # 使用 base64 图片
            yield res 