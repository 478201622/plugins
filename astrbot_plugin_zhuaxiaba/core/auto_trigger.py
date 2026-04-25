from __future__ import annotations

import time
import re
from typing import Optional

from astrbot.api import logger

from .config import ZhuaXiaBaPluginConfig


class AutoTriggerManager:
    """管理自动触发的冷却时间和关键词匹配"""
    
    def __init__(self, config: ZhuaXiaBaPluginConfig):
        self.cfg = config
        # 存储每个会话的最后触发时间: {session_id: timestamp}
        self._last_trigger_time: dict[str, float] = {}
    
    def should_trigger(self, message: str, session_id: str) -> bool:
        """
        判断是否应该自动触发
        
        Args:
            message: 用户消息内容
            session_id: 会话ID
            
        Returns:
            是否应该触发自动分享
        """
        if not self.cfg.auto_trigger_enabled:
            return False
        
        # 检查关键词匹配
        if not self._match_keywords(message):
            return False
        
        # 检查冷却时间
        # 移除冷却时间限制:         if not self._check_cooldown(session_id):
        #             return False
        
        return True
    
    def _match_keywords(self, message: str) -> bool:
        """检查消息是否包含触发关键词"""
        message_lower = message.lower()
        keywords = self.cfg.auto_trigger_keywords
        
        for keyword in keywords:
            if keyword.lower() in message_lower:
                return True
        return False
    
    def _check_cooldown(self, session_id: str) -> bool:
        """检查是否已过冷却时间"""
        current_time = time.time()
        last_time = self._last_trigger_time.get(session_id, 0)
        cooldown_seconds = self.cfg.auto_trigger_cooldown * 60
        
        if current_time - last_time < cooldown_seconds:
            return False
        
        return True
    
    def record_trigger(self, session_id: str):
        """记录触发时间"""
        self._last_trigger_time[session_id] = time.time()
        logger.info(f"[ZhuaXiaBaPlugin] 自动触发已记录，会话: {session_id}")
    
    def get_remaining_cooldown(self, session_id: str) -> int:
        """获取剩余冷却时间（分钟）"""
        current_time = time.time()
        last_time = self._last_trigger_time.get(session_id, 0)
        cooldown_seconds = self.cfg.auto_trigger_cooldown * 60
        remaining = cooldown_seconds - (current_time - last_time)
        
        if remaining <= 0:
            return 0
        return int(remaining / 60) + 1
