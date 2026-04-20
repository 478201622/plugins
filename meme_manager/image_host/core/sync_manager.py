from pathlib import Path

from tqdm import tqdm

from ..interfaces.image_host import ImageHostInterface
from .file_handler import FileHandler
from .upload_tracker import UploadTracker


class SyncManager:
    """同步管理器"""

    def __init__(
        self,
        image_host: ImageHostInterface,
        local_dir: Path,
        upload_tracker: UploadTracker | None = None,
    ):
        self.image_host = image_host
        self.file_handler = FileHandler(local_dir)
        self.upload_tracker = upload_tracker

    def _normalize_remote_id(self, remote_id: str, provider_name: str = None) -> str:
        """
        根据不同的图床提供商规范化远程文件ID

        Args:
            remote_id: 远程文件ID
            provider_name: 提供商名称

        Returns:
            规范化后的文件ID，用于与本地文件ID比较
        """
        if not provider_name:
            # 尝试从配置获取提供商名称
            if hasattr(self.image_host, "config") and self.image_host.config:
                provider_name = self.image_host.config.get("provider", "").lower()
            elif hasattr(self.image_host, "__class__"):
                provider_name = self.image_host.__class__.__name__.lower()

        # 统一转换为正斜杠
        normalized_id = remote_id.replace("\\", "/")

        # 根据不同提供商处理特定的前缀
        if provider_name:
            if "cloudflare_r2" in provider_name or "r2" in provider_name:
                # Cloudflare R2: 移除 memes/ 前缀
                if normalized_id.startswith("memes/"):
                    return normalized_id[6:]  # 移除"memes/"前缀
            elif "stardots" in provider_name:
                # Stardots: 保持原样（未来可能需要特殊处理）
                pass
            # 可以在这里添加其他提供商的处理逻辑

        return normalized_id

    def check_sync_status(self) -> dict[str, list[dict]]:
        """检查同步状态 - 简化版，只检查存在性"""
        print("正在扫描本地文件...")
        local_images = self.file_handler.scan_local_images()
        print(f"\n本地文件总数: {len(local_images)}")
        if len(local_images) > 5:
            print("前5个文件:")
            for img in local_images[:5]:
                print(f"  - [{img.get('category', '根目录')}] {img['filename']}")

        print("\n正在获取远程文件列表...")
        remote_images = self.image_host.get_image_list()
        print(f"\n远程文件总数: {len(remote_images)}")
        if len(remote_images) > 5:
            print("前5个文件:")
            for img in remote_images[:5]:
                print(f"  - [{img.get('category', '根目录')}] {img['filename']}")

        # 上传：检查哪些文件没有上传记录
        to_upload = []
        if self.upload_tracker:
            for img in local_images:
                category = img.get("category", "")
                file_path = Path(img["path"])
                if not self.upload_tracker.is_uploaded(file_path, category):
                    to_upload.append(img)
            print(f"\n未上传过的文件: {len(to_upload)} 个")
        else:
            # 如果没有上传追踪器，默认所有文件都需要上传
            to_upload = local_images
            print(f"\n未启用上传记录，所有文件标记为待上传: {len(to_upload)} 个")

        # 获取提供商名称
        provider_name = None
        if hasattr(self.image_host, "config") and self.image_host.config:
            provider_name = self.image_host.config.get("provider", "").lower()

        # 下载：检查哪些文件本地不存在
        local_file_ids = {img["id"].replace("\\", "/") for img in local_images}
        to_download = []
        for img in remote_images:
            remote_id = img["id"].replace("\\", "/")
            normalized_remote_id = self._normalize_remote_id(remote_id, provider_name)
            if normalized_remote_id not in local_file_ids:
                to_download.append(img)
        print(f"\n本地不存在的文件: {len(to_download)} 个")

        # 远程删除：检查哪些文件在云端存在但本地不存在
        to_delete_remote = to_download.copy() 
        print(f"\n云端多出的文件: {len(to_delete_remote)} 个")

        # 本地删除：检查哪些文件在本地存在但云端不存在
        remote_file_ids = set()
        for img in remote_images:
            remote_id = img["id"].replace("\\", "/")
            normalized_remote_id = self._normalize_remote_id(remote_id, provider_name)
            remote_file_ids.add(normalized_remote_id)

        to_delete_local = []
        for img in local_images:
            local_id = img["id"].replace("\\", "/")
            if local_id not in remote_file_ids:
                to_delete_local.append(img)
        print(f"\n本地多出的文件: {len(to_delete_local)} 个")

        return {
            "to_upload": to_upload,
            "to_download": to_download,
            "to_delete_local": to_delete_local,
            "to_delete_remote": to_delete_remote,
            "is_synced": not (to_upload or to_download or to_delete_local or to_delete_remote),
        }

    def sync_to_remote(self) -> bool:
        """同步本地文件到远程 - 只上传未上传过的文件"""
        status = self.check_sync_status()

        if status.get("is_synced", False):
            print("\n所有文件已上传，无需重复上传")
            return True

        # 上传新文件
        to_upload = status["to_upload"]
        if to_upload:
            print(f"\n开始上传 {len(to_upload)} 个文件...")
            uploaded_count = 0
            skipped_count = 0

            with tqdm(total=len(to_upload), desc="上传进度") as pbar:
                for image in to_upload:
                    file_path = Path(image["path"])
                    category = image.get("category", "")

                    try:
                        # 上传文件
                        result = self.image_host.upload_image(file_path)

                        # 记录已上传
                        if self.upload_tracker:
                            remote_url = result.get("url", "")
                            self.upload_tracker.mark_uploaded(
                                file_path, category, remote_url
                            )

                        uploaded_count += 1
                        pbar.update(1)

                    except Exception as e:
                        print(f"\n上传失败: {file_path.name} - {str(e)}")
                        skipped_count += 1
                        pbar.update(1)

            print(f"\n上传完成: 成功 {uploaded_count} 个，失败 {skipped_count} 个")
        else:
            print("\n没有需要上传的文件")

        return True

    def sync_from_remote(self) -> bool:
        """从远程同步文件到本地 - 只下载本地不存在的文件"""
        status = self.check_sync_status()

        if status.get("is_synced", False):
            print("\n所有文件已存在，无需下载")
            return True

        # 下载新文件
        to_download = status["to_download"]
        if to_download:
            print(f"\n开始下载 {len(to_download)} 个文件...")
            downloaded_count = 0
            skipped_count = 0

            with tqdm(total=len(to_download), desc="下载进度") as pbar:
                for image in to_download:
                    try:
                        # 使用图片信息中的分类
                        category = image.get("category", "")
                        filename = image["filename"]

                        # 获取保存路径
                        save_path = self.file_handler.get_file_path(category, filename)

                        # 检查文件是否已存在（双重检查）
                        if save_path.exists():
                            print(f"文件已存在，跳过: {filename}")
                            skipped_count += 1
                            pbar.update(1)
                            continue

                        if self.image_host.download_image(image, save_path):
                            downloaded_count += 1
                            pbar.update(1)
                        else:
                            print(f"\n下载失败: {filename}")
                            skipped_count += 1
                            pbar.update(1)
                    except Exception as e:
                        print(f"\n下载失败: {filename} - {str(e)}")
                        skipped_count += 1
                        pbar.update(1)

            print(
                f"\n下载完成: 成功 {downloaded_count} 个，失败/跳过 {skipped_count} 个"
            )
        else:
            print("\n没有需要下载的文件")

        return True

    def overwrite_to_remote(self) -> bool:
        """从本地覆盖云端 - 让云端完全和本地一致"""
        status = self.check_sync_status()

        # 1. 上传本地多出的文件
        self.sync_to_remote()

        # 2. 删除云端多出的文件
        to_delete_remote = status.get("to_delete_remote", [])
        if to_delete_remote:
            print(f"\n开始清理云端多出的 {len(to_delete_remote)} 个文件...")
            deleted_count = 0
            for img in tqdm(to_delete_remote, desc="清理云端"):
                try:
                    if self.image_host.delete_image(img["id"]):
                        deleted_count += 1
                except Exception as e:
                    print(f"\n删除云端文件失败: {img['filename']} - {str(e)}")
            print(f"\n云端清理完成: 成功删除 {deleted_count} 个")
        else:
            print("\n云端没有多出的文件，无需清理")

        return True

    def overwrite_from_remote(self) -> bool:
        """从云端覆盖本地 - 让本地完全和云端一致"""
        status = self.check_sync_status()

        # 1. 下载本地缺失的文件
        self.sync_from_remote()

        # 2. 删除本地多出的文件
        to_delete_local = status.get("to_delete_local", [])
        if to_delete_local:
            print(f"\n开始清理本地多出的 {len(to_delete_local)} 个文件...")
            deleted_count = 0
            for img in tqdm(to_delete_local, desc="清理本地"):
                try:
                    file_path = Path(img["path"])
                    if file_path.exists():
                        file_path.unlink()
                        deleted_count += 1
                        # 同时从上传记录中移除
                        if self.upload_tracker:
                            self.upload_tracker.remove_record(file_path, img.get("category", ""))
                except Exception as e:
                    print(f"\n删除本地文件失败: {img['filename']} - {str(e)}")
            print(f"\n本地清理完成: 成功删除 {deleted_count} 个")
        else:
            print("\n本地没有多出的文件，无需清理")

        return True
