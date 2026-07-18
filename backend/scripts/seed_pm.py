"""PM Hub 预置数据 seed 脚本（设计稿 §5.7：迁移 + seed 脚本一次性写入）。

用法（在 backend/ 目录下）：
    python scripts/seed_pm.py           # 幂等写入：项目/白名单/35 项材料/14 条行动任务
    python scripts/seed_pm.py --reset   # 清空 pm 业务数据后重灌（材料清单核对修正后用）

幂等口径：项目按 code upsert；白名单按 username 补缺（不动已有行）；
材料/任务只在「该项目下一条都没有」时写入，避免覆盖人工改动。--reset 物理删除
ark_pm_materials/versions/tasks/task_materials/activity_logs 后重新 seed。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.pm.models import (  # noqa: E402
    PmActivityLog, PmMaterial, PmMaterialVersion, PmMember, PmProject, PmTask, PmTaskMaterial, bj_now,
)
from app.pm.seed_data import MATERIALS_SEED, MEMBERS_SEED, PROJECT_SEED, TASKS_SEED  # noqa: E402


def reset(db, project: PmProject | None) -> None:
    if not project:
        print("[seed_pm] 项目不存在，无需 reset")
        return
    pid = project.id
    for model, field in (
        (PmActivityLog, "project_id"),
        (PmTaskMaterial, None),
        (PmTask, "project_id"),
        (PmMaterialVersion, None),
        (PmMaterial, "project_id"),
    ):
        if field:
            count = db.query(model).filter(getattr(model, field) == pid).delete(synchronize_session=False)
        elif model is PmTaskMaterial:
            count = db.query(PmTaskMaterial).filter(
                PmTaskMaterial.task_id.in_(db.query(PmTask.id).filter(PmTask.project_id == pid))
            ).delete(synchronize_session=False)
        else:  # PmMaterialVersion
            count = db.query(PmMaterialVersion).filter(
                PmMaterialVersion.material_id.in_(db.query(PmMaterial.id).filter(PmMaterial.project_id == pid))
            ).delete(synchronize_session=False)
        print(f"[seed_pm] reset {model.__tablename__}: {count} 行")
    db.commit()


def seed() -> None:
    do_reset = "--reset" in sys.argv
    with SessionLocal() as db:
        project = db.query(PmProject).filter(PmProject.code == PROJECT_SEED["code"]).first()
        if do_reset:
            reset(db, project)  # 清业务数据，项目行保留
        # 1. 项目（upsert）
        project = db.query(PmProject).filter(PmProject.code == PROJECT_SEED["code"]).first()
        if not project:
            project = PmProject(**PROJECT_SEED)
            db.add(project)
            db.flush()
            print(f"[seed_pm] 创建项目 {PROJECT_SEED['name']} (id={project.id})")
        else:
            print(f"[seed_pm] 项目已存在 (id={project.id})，跳过")

        # 2. 白名单（按 username 补缺）
        existing = {m.username for m in db.query(PmMember).all()}
        added = 0
        for username, display_name in MEMBERS_SEED:
            if username not in existing:
                db.add(PmMember(username=username, display_name=display_name))
                added += 1
        print(f"[seed_pm] 白名单新增 {added} 人（已有 {len(existing)} 人不动）")

        # 3. 35 项材料（仅当项目下为空）
        material_count = db.query(PmMaterial).filter(PmMaterial.project_id == project.id).count()
        if material_count == 0:
            for i, (list_no, name, category, importance, phase, delivery_type, desc) in enumerate(MATERIALS_SEED):
                db.add(PmMaterial(
                    project_id=project.id, list_no=list_no, name=name, category=category,
                    importance=importance, phase=phase, delivery_type=delivery_type,
                    description=desc, sort_order=i,
                ))
            print(f"[seed_pm] 写入材料 {len(MATERIALS_SEED)} 项")
        else:
            print(f"[seed_pm] 材料已存在 {material_count} 项，跳过（要重灌用 --reset）")

        # 4. 行动清单任务（仅当项目下为空）
        db.flush()
        task_count = db.query(PmTask).filter(PmTask.project_id == project.id).count()
        if task_count == 0:
            no_to_id = {
                m.list_no: m.id
                for m in db.query(PmMaterial).filter(PmMaterial.project_id == project.id).all()
            }
            for i, (title, desc, phase, link_nos) in enumerate(TASKS_SEED):
                task = PmTask(
                    project_id=project.id, title=title, description=desc,
                    status="todo", phase=phase, sort_order=i, created_by="seed",
                )
                db.add(task)
                db.flush()
                for link_no in link_nos:
                    if link_no in no_to_id:
                        db.add(PmTaskMaterial(task_id=task.id, material_id=no_to_id[link_no], created_at=bj_now()))
            print(f"[seed_pm] 写入行动任务 {len(TASKS_SEED)} 条")
        else:
            print(f"[seed_pm] 任务已存在 {task_count} 条，跳过")

        db.commit()
        print("[seed_pm] done")
        if do_reset:
            print("[seed_pm] 提示：backend/data/pm/ 下的旧文件仍在盘上（软删原则保留），确认无用后可手动清理")


if __name__ == "__main__":
    seed()
