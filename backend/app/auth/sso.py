"""钉钉 SSO 预留接口（v2 实现）"""


class SSOProvider:
    async def authenticate(self, code: str) -> dict:
        """
        v2 实现：用钉钉 OAuth code 换取用户信息
        返回: { "dingtalk_id": str, "name": str, "mobile": str }
        """
        raise NotImplementedError("Dingtalk SSO not implemented in v1")
