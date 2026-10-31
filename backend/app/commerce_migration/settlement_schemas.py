"""A reviewed closure request contains identities, never claimed zero balances."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SettledInvoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    invoice_id: int = Field(gt=0)
    expected_authority_epoch: int = Field(ge=1)


class SettlementManifest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_reference: str = Field(min_length=1, max_length=500)
    invoices: list[SettledInvoice] = Field(default_factory=list, max_length=200)
    bank_identity_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=200)

    @model_validator(mode='after')
    def unique_objects(self):
        if not self.invoices and not self.bank_identity_ids:
            raise ValueError('必须选择实际原责任对象')
        if (len({r.invoice_id for r in self.invoices}) != len(self.invoices)
                or len(set(self.bank_identity_ids)) != len(self.bank_identity_ids)):
            raise ValueError('结清对象不能重复')
        return self
