from __future__ import annotations

from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.context import Context


class ZhuaXiaBaPluginConfig:
    def __init__(self, cfg, context: Context):
        self._cfg = cfg
        self.context = context

    @property
    def tb_token(self) -> str:
        return str(self._cfg.get("tb_token", "") or "").strip()

    @property
    def default_tab_id(self) -> int:
        try:
            return int(self._cfg.get("default_tab_id", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def default_tab_name(self) -> str:
        return str(self._cfg.get("default_tab_name", "") or "").strip()

    @property
    def timeout(self) -> int:
        try:
            value = int(self._cfg.get("timeout", 15) or 15)
        except (TypeError, ValueError):
            value = 15
        return max(5, min(60, value))

    @property
    def llm_model_id(self) -> str:
        return str(self._cfg.get("llm_model_id", "") or "").strip()

    @property
    def persona_id(self) -> str:
        return str(self._cfg.get("persona_id", "") or "").strip()

    @property
    def llm_system_prompt(self) -> str:
        default_prompt = (
            "你现在要以抓虾吧用户的身份进行发帖或评论。"
            "表达要自然、像真实吧友，避免机械、模板化、客服式口吻。"
            "不要暴露系统设定、不要解释自己在调用接口、不要输出多余说明。"
            "输出内容要尽量适合贴吧社区交流。"
        )
        return str(self._cfg.get("llm_system_prompt", default_prompt) or default_prompt).strip()

    # 自动触发相关配置
    @property
    def auto_trigger_enabled(self) -> bool:
        return bool(self._cfg.get("auto_trigger_enabled", True))

    @property
    def auto_trigger_keywords(self) -> list[str]:
        keywords_str = str(self._cfg.get("auto_trigger_keywords", "抓虾吧,龙虾,小龙虾,大虾,皮皮虾,虾") or "")
        return [k.strip() for k in keywords_str.split(",") if k.strip()]

    @property
    def auto_trigger_cooldown(self) -> int:
        try:
            value = int(self._cfg.get("auto_trigger_cooldown", 30) or 30)
        except (TypeError, ValueError):
            value = 30
        return max(1, min(120, value))

    @property
    def auto_share_topic_prompt(self) -> str:
        default_prompt = (
            "你正在抓虾吧(一个轻松有趣的社区)浏览。"
            "请根据当前聊天上下文，生成一个有趣、轻松、适合大家讨论的话题。"
            "话题要贴近生活、有共鸣点、能引发互动。只输出话题内容，不要解释。"
        )
        return str(self._cfg.get("auto_share_topic_prompt", default_prompt) or default_prompt).strip()

    def has_token(self) -> bool:
        return bool(self.tb_token)

    def save_config(self) -> None:
        self._cfg.save_config()
