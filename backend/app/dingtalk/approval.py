"""钉钉审批操作 — 发起、查询、终止审批实例"""

import logging
from typing import Optional

from app.dingtalk.client import get_dingtalk_client, DingTalkError

logger = logging.getLogger("commission.dingtalk")


class ApprovalService:
    """钉钉审批流操作（Phase 2 — 需企业内部应用）"""

    async def start_instance(
        self,
        process_code: str,
        originator_user_id: str,
        form_values: dict,
        approver_user_ids: list[list[str]],
        cc_user_ids: Optional[list[str]] = None,
    ) -> str:
        """
        发起审批实例。

        process_code: 审批流模板唯一码
        originator_user_id: 发起人 UserID
        form_values: 表单控件值 {"控件ID": {"value": "内容"}}
        approver_user_ids: 审批人列表（每层一个 list）  [["user1"], ["user2", "user3"]]
            单人审批: [["user1"]]
            会签:     [["user1", "user2"]]
            多级审批: [["user1"], ["user2"]]
        cc_user_ids: 抄送人 UserID 列表

        Returns: 审批实例 ID
        """
        client = get_dingtalk_client()
        body = {
            "process_code": process_code,
            "originator_user_id": originator_user_id,
            "form_component_values": self._build_form_values(form_values),
            "approvers": approver_user_ids,
        }
        if cc_user_ids:
            body["cc_list"] = ",".join(cc_user_ids)
            body["cc_position"] = "FINISH"

        data = await client.post("topapi/processinstance/create", json_data=body)
        instance_id = data.get("result", {}).get("process_instance_id")
        logger.info("钉钉审批已发起: instance_id=%s", instance_id)
        return instance_id

    async def get_instance(self, instance_id: str) -> dict:
        """查询审批实例详情"""
        client = get_dingtalk_client()
        data = await client.post(
            "topapi/processinstance/get",
            json_data={"process_instance_id": instance_id},
        )
        return data.get("result", {}).get("process_instance", {})

    async def get_instance_status(self, instance_id: str) -> str:
        """查询审批实例状态: NEW/RUNNING/TERMINATED/COMPLETED/COMPLETED_AND_REJECTED"""
        instance = await self.get_instance(instance_id)
        return instance.get("status", "UNKNOWN")

    async def terminate_instance(self, instance_id: str, is_system: bool = False) -> bool:
        """
        终止审批实例。
        is_system: 是否系统操作（不发通知）
        """
        client = get_dingtalk_client()
        body = {
            "process_instance_id": instance_id,
            "is_system": is_system,
        }
        try:
            await client.post("topapi/processinstance/terminate", json_data=body)
            logger.info("审批实例已终止: %s", instance_id)
            return True
        except DingTalkError as e:
            logger.error("终止审批实例失败: %s", e)
            return False

    @staticmethod
    def _build_form_values(form_values: dict) -> list[dict]:
        """
        将简单的 {key: value} 转换为钉钉要求的表单格式。
        钉钉表单格式: [{"componentName": "TextField", "props": {"id": "控件ID", "label": "..."}, "value": "值"}]
        """
        result = []
        for key, value in form_values.items():
            item = {
                "componentName": "TextField",
                "props": {"id": key, "label": key},
                "value": str(value),
            }
            result.append(item)
        return result


_approval_service: ApprovalService | None = None


def get_approval_service() -> ApprovalService:
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service
