"""素材管理 — service facade

新代码建议直接 import 子模块:
  from app.asset.tag_service import list_dimensions, ...
  from app.asset.asset_service import create_asset, query_assets, ...

保留 facade 兼容历史调用方:
  from app.asset.service import create_asset, ...
"""

# 标签服务
from app.asset.tag_service import (  # noqa: F401
    list_dimensions,
    get_dimension,
    create_dimension,
    update_dimension,
    delete_dimension,
    create_dimension_value,
    update_dimension_value,
    delete_dimension_value,
    seed_default_dimensions,
)

# 素材服务
from app.asset.asset_service import (  # noqa: F401
    create_asset,
    query_assets,
    get_asset_detail,
    update_asset_tags,
    update_asset_status,
    upload_new_version,
    delete_asset,
    get_asset_download_url,
    increment_download_count,
)

# 批量服务
from app.asset.batch_service import (  # noqa: F401
    batch_download,
)

# 统计服务
from app.asset.stats_service import (  # noqa: F401
    get_download_stats,
    get_top_downloaded,
    get_download_trend,
)

# 文件夹上传服务
from app.asset.folder_upload_service import (  # noqa: F401
    scan_folder,
    extract_tags_from_path,
    validate_folder_tags,
    preview_files,
    execute_folder_upload,
)

# 收藏服务
from app.asset.favorite_service import (  # noqa: F401
    list_favorite_folders,
    create_favorite_folder,
    update_favorite_folder,
    delete_favorite_folder,
    list_favorite_items,
    add_favorite_item,
    remove_favorite_item,
    remove_favorite_item_by_asset,
    share_folder,
    get_shared_folder,
    revoke_share,
)
