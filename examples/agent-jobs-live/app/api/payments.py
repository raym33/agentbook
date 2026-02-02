"""Payments API routes - Stripe and Crypto."""
from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, AgentNode
from app.schemas import (
    StripeCheckoutCreate, StripeCheckoutResponse,
    StripePayoutRequest, CryptoDepositInfo, CryptoPayoutRequest
)
from app.services.auth import get_current_company
from app.services.payments import get_stripe_service, get_crypto_service

router = APIRouter(prefix="/payments", tags=["payments"])


def get_agent_from_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db)
) -> AgentNode:
    """Authenticate agent node by API key."""
    agent = db.query(AgentNode).filter(AgentNode.api_key == x_api_key).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return agent


# ============ Company - Add Funds ============

@router.post("/stripe/checkout", response_model=dict)
def create_stripe_checkout(
    data: StripeCheckoutCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """
    Create a Stripe Checkout session to add funds.

    Returns a checkout URL where the company can enter payment details.
    After successful payment, funds are added to company balance.
    """
    stripe_service = get_stripe_service(db)

    try:
        result = stripe_service.create_checkout_session(
            company=company,
            amount=data.amount,
            success_url=data.success_url,
            cancel_url=data.cancel_url,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Stripe webhook events.

    Stripe calls this endpoint when payment is completed.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    stripe_service = get_stripe_service(db)

    try:
        stripe_service.handle_webhook(payload.decode(), signature)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/crypto/deposit-info", response_model=dict)
def get_crypto_deposit_info(
    network: str = "ethereum",
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """
    Get deposit address for adding funds via crypto.

    Supported networks: ethereum, polygon, arbitrum
    Supported tokens: USDC, USDT, ETH
    """
    crypto_service = get_crypto_service(db)

    try:
        return crypto_service.get_deposit_info(company, network)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/crypto/verify-deposit")
def verify_crypto_deposit(
    tx_hash: str,
    network: str = "ethereum",
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """
    Verify a crypto deposit transaction and credit balance.

    After sending crypto to the deposit address, call this endpoint
    with the transaction hash to credit your account.
    """
    crypto_service = get_crypto_service(db)

    try:
        result = crypto_service.verify_deposit(tx_hash, network)
        if result and result.get("verified"):
            company.balance += result["amount"]
            db.commit()
            return {
                "status": "credited",
                "amount": result["amount"],
                "new_balance": company.balance,
                **result
            }
        return {"status": "pending", "message": "Transaction not yet confirmed"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============ Agent - Withdrawals ============

@router.get("/agent/balance")
def get_agent_balance(
    agent: AgentNode = Depends(get_agent_from_key),
):
    """Get agent's current earnings and payout balance."""
    return {
        "total_earned": agent.total_earned,
        "pending_payout": agent.pending_payout,
        "jobs_completed": agent.jobs_completed,
        "wallet_address": agent.wallet_address,
    }


@router.post("/agent/payout/stripe")
def request_stripe_payout(
    data: StripePayoutRequest,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """
    Request payout via Stripe.

    Requires agent to have a connected Stripe account.
    """
    if data.amount > agent.pending_payout:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. Available: ${agent.pending_payout:.2f}"
        )

    stripe_service = get_stripe_service(db)

    try:
        result = stripe_service.create_payout(agent, data.amount)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/agent/payout/crypto")
def request_crypto_payout(
    data: CryptoPayoutRequest,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """
    Request payout via crypto (USDC, USDT, or ETH).

    Supported networks: ethereum, polygon, arbitrum
    """
    if data.amount > agent.pending_payout:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. Available: ${agent.pending_payout:.2f}"
        )

    crypto_service = get_crypto_service(db)

    # Get gas estimate first
    gas_estimate = crypto_service.estimate_gas(data.network, data.token)

    try:
        result = crypto_service.create_payout(
            agent=agent,
            amount=data.amount,
            wallet_address=data.wallet_address,
            token=data.token,
            network=data.network,
        )
        result["gas_fee"] = gas_estimate
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/agent/payout/gas-estimate")
def estimate_gas(
    network: str = "ethereum",
    token: str = "USDC",
    db: Session = Depends(get_db)
):
    """Estimate gas fees for a crypto payout."""
    crypto_service = get_crypto_service(db)
    return crypto_service.estimate_gas(network, token)


@router.put("/agent/wallet")
def update_wallet_address(
    wallet_address: str,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Update agent's wallet address for crypto payouts."""
    # Basic validation
    if not wallet_address.startswith("0x") or len(wallet_address) != 42:
        raise HTTPException(status_code=400, detail="Invalid Ethereum address format")

    agent.wallet_address = wallet_address
    db.commit()

    return {"message": "Wallet address updated", "wallet_address": wallet_address}


# ============ Company - Balance Info ============

@router.get("/company/balance")
def get_company_balance(
    company: Company = Depends(get_current_company),
):
    """Get company's current balance and spending stats."""
    return {
        "balance": company.balance,
        "total_spent": company.total_spent,
        "jobs_posted": company.jobs_posted,
        "jobs_completed": company.jobs_completed,
    }
