"""数据模型汇总导入"""

from app.models.employee import EmployeeAttributeHistory, SupervisorRelationHistory
from app.models.customer import CustomerCommissionSnapshot
from app.models.commission import (
    SyncedPayment, CommissionBatch, CommissionDetail, PaymentCommissionStatus,
)
from app.models.business import UserBasic, CustomerInfo, OkkiOrder, OkkiReceipt
from app.tracking.models import (
    ShipmentStaging, ShipmentTracking, TrackingEvent, CarrierConfig,
)
from app.tracking.models import Waybill
from app.models.short_link import ArkShortLink
from app.aftersales.models import (
    AfterSalesCase,
    AfterSalesEvidence,
    AfterSalesAiRun,
    AfterSalesReview,
    AfterSalesEvent,
    AfterSalesSopVersion,
    AfterSalesNotificationLog,
)
from app.design_image.models import (
    DesignImageSession,
    DesignImageMessage,
    DesignImageAsset,
    DesignImageJob,
    DesignImageJobAsset,
)
from app.customer_image.models import (
    CustomerImageProduct,
    CustomerImageProductAsset,
    CustomerImageProductOption,
    CustomerImageOptionValue,
    CustomerImageInvite,
    CustomerImageInviteProduct,
    CustomerImageAsset,
    CustomerImageGeneration,
)
from app.ai_chat.models import AiChatSession, AiChatMessage, AiChatAttachment
from app.customer.models import (
    CustomerAccount,
    CustomerName,
    CustomerExternalIdentity,
    CustomerRelationship,
    CustomerAssignment,
    CustomerContact,
    CustomerContactPoint,
    CustomerContactRelationship,
    CustomerSourceRecord,
    CustomerFact,
    CustomerEvent,
    CustomerAnnotation,
    CustomerQualificationReview,
    CustomerProfileVersion,
    CustomerAgentContext,
    CustomerConversation,
    CustomerMessage,
    CustomerConversationAnalysis,
    CustomerOrder,
    CustomerOrderItem,
    CustomerResearchTask,
    CustomerSyncCursor,
    CustomerFactEvidenceLink,
    CustomerFactConflict,
    CustomerListProjection,
    CustomerChangeProposal,
    CustomerAgentRunScope,
    CustomerSuppressionRegistry,
    CustomerResolutionKey,
    CustomerTargetMatch,
    CustomerAcquisitionAttribution,
)
from app.sales_automation.models import (
    AcquisitionProfile,
    SearchJob,
    LeadCompany,
    ResearchSubject,
    PublicPoolBatch,
    PublicPoolTask,
    DealAssessment,
    SearchResult,
    LeadContact,
    ResearchRun,
    ResearchFact,
)
from app.knowledge.models import (
    KnowledgeLibrary,
    KnowledgeLibraryMember,
    KnowledgeDocument,
    KnowledgeRevision,
    KnowledgeApprovalRequest,
    KnowledgeAuditLog,
)
from app.order_intelligence.models import OrderIntelligenceBriefJob
from app.operations.db_models import (
    JobRun,
    OperationAudit,
    RuntimeHeartbeat,
    RuntimeInstance,
    SchedulerJobPolicy,
)
from app.customer_media.models import (
    CustomerMediaBatch,
    CustomerMediaAsset,
    CustomerMediaReview,
    CustomerPortalAccount,
    CustomerPortalSession,
    CustomerMediaDownload,
)
from app.agent_runtime.models import (
    AgentProfile,
    AgentSession,
    AgentRun,
    AgentEvent,
    AgentArtifact,
)
from app.semifinished.models import (
    CartPlan,
    InventoryBalance,
    InventoryLedger,
    InvoiceAllocation,
    ProductComponent,
    ProductMapping,
    SemifinishedMaterial,
    SemifinishedOrder,
    SemifinishedOrderItem,
)
from app.integration.models import IntegrationApp, InvoiceIngestRequest

__all__ = [
    # 提成系统自有表
    "EmployeeAttributeHistory",
    "SupervisorRelationHistory",
    "CustomerCommissionSnapshot",
    "SyncedPayment",
    "CommissionBatch",
    "CommissionDetail",
    "PaymentCommissionStatus",
    # 业务库只读映射
    "UserBasic",
    "CustomerInfo",
    "OkkiOrder",
    "OkkiReceipt",
    # 物流跟踪
    "ShipmentStaging",
    "ShipmentTracking",
    "TrackingEvent",
    "CarrierConfig",
    # 运单录入
    "Waybill",
    # 短链接
    "ArkShortLink",
    # 客户售后管理
    "AfterSalesCase",
    "AfterSalesEvidence",
    "AfterSalesAiRun",
    "AfterSalesReview",
    "AfterSalesEvent",
    "AfterSalesSopVersion",
    "AfterSalesNotificationLog",
    # AI 生图工作台
    "DesignImageSession",
    "DesignImageMessage",
    "DesignImageAsset",
    "DesignImageJob",
    "DesignImageJobAsset",
    # 客户产品效果图门户
    "CustomerImageProduct",
    "CustomerImageProductAsset",
    "CustomerImageProductOption",
    "CustomerImageOptionValue",
    "CustomerImageInvite",
    "CustomerImageInviteProduct",
    "CustomerImageAsset",
    "CustomerImageGeneration",
    # AI 方案对话
    "AiChatSession",
    "AiChatMessage",
    "AiChatAttachment",
    # Unified customer core
    "CustomerAccount",
    "CustomerName",
    "CustomerExternalIdentity",
    "CustomerRelationship",
    "CustomerAssignment",
    "CustomerContact",
    "CustomerContactPoint",
    "CustomerContactRelationship",
    "CustomerSourceRecord",
    "CustomerFact",
    "CustomerEvent",
    "CustomerAnnotation",
    "CustomerQualificationReview",
    "CustomerProfileVersion",
    "CustomerAgentContext",
    "CustomerConversation",
    "CustomerMessage",
    "CustomerConversationAnalysis",
    "CustomerOrder",
    "CustomerOrderItem",
    "CustomerResearchTask",
    "CustomerSyncCursor",
    "CustomerFactEvidenceLink",
    "CustomerFactConflict",
    "CustomerListProjection",
    "CustomerChangeProposal",
    "CustomerAgentRunScope",
    "CustomerSuppressionRegistry",
    "CustomerResolutionKey",
    "CustomerTargetMatch",
    "CustomerAcquisitionAttribution",
    # 智能获客
    "AcquisitionProfile",
    "SearchJob",
    "LeadCompany",
    "ResearchSubject",
    "PublicPoolBatch",
    "PublicPoolTask",
    "DealAssessment",
    "SearchResult",
    "LeadContact",
    "ResearchRun",
    "ResearchFact",
    # Knowledge base
    "KnowledgeLibrary",
    "KnowledgeLibraryMember",
    "KnowledgeDocument",
    "KnowledgeRevision",
    "KnowledgeApprovalRequest",
    "KnowledgeAuditLog",
    # 订单经营 AI 简报
    "OrderIntelligenceBriefJob",
    # 运行与自动化中心
    "JobRun",
    "OperationAudit",
    "RuntimeHeartbeat",
    "RuntimeInstance",
    "SchedulerJobPolicy",
    "CustomerMediaBatch",
    "CustomerMediaAsset",
    "CustomerMediaReview",
    "CustomerPortalAccount",
    "CustomerPortalSession",
    "CustomerMediaDownload",
    # AI Agent 控制面
    "AgentProfile",
    "AgentSession",
    "AgentRun",
    "AgentEvent",
    "AgentArtifact",
    # 半成品订单与库存
    "SemifinishedMaterial",
    "ProductMapping",
    "ProductComponent",
    "SemifinishedOrder",
    "SemifinishedOrderItem",
    "InventoryBalance",
    "InventoryLedger",
    "CartPlan",
    "InvoiceAllocation",
    # 外部发票接入
    "IntegrationApp",
    "InvoiceIngestRequest",
]
