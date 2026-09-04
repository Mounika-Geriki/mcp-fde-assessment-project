import logging
import re
import sys
from typing import Dict

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator

# IMPORTANT: logs are explicitly sent to stderr so stdout remains pure MCP JSON-RPC.
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP("fde-customer-tools")

CUSTOMERS: Dict[str, dict] = {
    "CUST-00001": {"customer_id": "CUST-00001", "name": "Alice Example", "status": "active"},
    "CUST-00002": {"customer_id": "CUST-00002", "name": "Bob Example", "status": "active"},
}

CUSTOMER_PATTERN = re.compile(r"^CUST-\d{5}$")


class CustomerRecordInput(BaseModel):
    customer_id: str

    @field_validator("customer_id")
    @classmethod
    def validate_customer_id(cls, value: str) -> str:
        if not CUSTOMER_PATTERN.fullmatch(value):
            raise ValueError("customer_id must match CUST-XXXXX where X is a digit")
        return value


class RefundInput(BaseModel):
    customer_id: str
    amount: float = Field(gt=0)
    reason: str = Field(min_length=10)

    @field_validator("customer_id")
    @classmethod
    def validate_customer_id(cls, value: str) -> str:
        if not CUSTOMER_PATTERN.fullmatch(value):
            raise ValueError("customer_id must match CUST-XXXXX where X is a digit")
        return value


@mcp.tool()
def get_customer_record(customer_id: str) -> dict:
    validated = CustomerRecordInput(customer_id=customer_id)
    logger.info("get_customer_record called for %s", validated.customer_id)
    return CUSTOMERS.get(
        validated.customer_id,
        {"customer_id": validated.customer_id, "status": "not_found"},
    )


@mcp.tool()
def trigger_refund(customer_id: str, amount: float, reason: str) -> dict:
    validated = RefundInput(customer_id=customer_id, amount=amount, reason=reason)
    logger.info("trigger_refund called for %s", validated.customer_id)
    return {
        "status": "accepted",
        "customer_id": validated.customer_id,
        "amount": validated.amount,
        "reason": validated.reason,
    }


if __name__ == "__main__":
    # FastMCP uses stdio transport by default when run this way.
    mcp.run(transport="stdio")
