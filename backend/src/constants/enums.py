from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class SyncRoundStatus(str, Enum):
    syncing = 'syncing'          # 待接续
    reconciling = 'reconciling'  # 核对中
    blocked = 'blocked'          # 缺页或版本冲突，已阻断发布
    failed = 'failed'            # 执行异常，可恢复
    published = 'published'      # 已发布
