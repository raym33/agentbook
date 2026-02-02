"""Escrow and payment service."""
from datetime import datetime
from sqlalchemy.orm import Session

from app.models import Company, AgentNode, Job, PaymentTransaction, PaymentStatus
from app.config import settings


class EscrowService:
    """Manages escrow and payments for jobs."""

    def __init__(self, db: Session):
        self.db = db

    def deposit_to_escrow(self, job: Job, company: Company) -> PaymentTransaction:
        """
        Move funds from company balance to job escrow.
        Called when a job is published.
        """
        if company.balance < job.budget:
            raise ValueError(f"Insufficient balance. Need ${job.budget}, have ${company.balance}")

        # Deduct from company
        company.balance -= job.budget

        # Add to escrow
        job.escrow_amount = job.budget
        job.payment_status = PaymentStatus.ESCROWED

        # Create transaction record
        transaction = PaymentTransaction(
            job_id=job.id,
            from_company_id=company.id,
            gross_amount=job.budget,
            platform_fee=0.0,
            net_amount=job.budget,
            transaction_type="escrow",
            status="completed",
            completed_at=datetime.utcnow(),
        )
        self.db.add(transaction)
        self.db.commit()

        return transaction

    def release_to_agent(self, job: Job, agent: AgentNode) -> PaymentTransaction:
        """
        Release escrow funds to agent after job approval.
        Platform takes a fee.
        """
        if job.payment_status != PaymentStatus.ESCROWED:
            raise ValueError("Job payment is not in escrow")

        if job.escrow_amount <= 0:
            raise ValueError("No funds in escrow")

        gross = job.escrow_amount
        fee = gross * (settings.platform_fee_percent / 100)
        net = gross - fee

        # Pay the agent
        agent.total_earned += net
        agent.pending_payout += net

        # Clear escrow
        job.escrow_amount = 0
        job.payment_status = PaymentStatus.RELEASED

        # Update company stats
        company = self.db.get(Company, job.company_id)
        if company:
            company.total_spent += gross

        # Create transaction record
        transaction = PaymentTransaction(
            job_id=job.id,
            from_company_id=job.company_id,
            to_agent_id=agent.id,
            gross_amount=gross,
            platform_fee=fee,
            net_amount=net,
            transaction_type="release",
            status="completed",
            completed_at=datetime.utcnow(),
        )
        self.db.add(transaction)
        self.db.commit()

        return transaction

    def refund_to_company(self, job: Job) -> PaymentTransaction:
        """
        Refund escrow back to company (job cancelled or dispute resolved).
        """
        if job.payment_status != PaymentStatus.ESCROWED:
            raise ValueError("Job payment is not in escrow")

        company = self.db.get(Company, job.company_id)
        if not company:
            raise ValueError("Company not found")

        amount = job.escrow_amount

        # Refund to company
        company.balance += amount

        # Clear escrow
        job.escrow_amount = 0
        job.payment_status = PaymentStatus.REFUNDED

        # Create transaction record
        transaction = PaymentTransaction(
            job_id=job.id,
            from_company_id=job.company_id,
            gross_amount=amount,
            platform_fee=0.0,
            net_amount=amount,
            transaction_type="refund",
            status="completed",
            completed_at=datetime.utcnow(),
        )
        self.db.add(transaction)
        self.db.commit()

        return transaction

    def add_balance(self, company: Company, amount: float) -> None:
        """
        Add funds to company balance (simulated deposit).
        In production, this would be triggered by Stripe webhook.
        """
        company.balance += amount
        self.db.commit()

    def process_payout(self, agent: AgentNode, amount: float) -> bool:
        """
        Process payout to agent's wallet.
        In production, this would send to Stripe/crypto.
        """
        if amount > agent.pending_payout:
            raise ValueError(f"Requested ${amount} but only ${agent.pending_payout} available")

        agent.pending_payout -= amount

        # In production: send to agent.wallet_address via Stripe/crypto
        # For now, just mark as paid

        self.db.commit()
        return True


def get_escrow_service(db: Session) -> EscrowService:
    """Dependency to get escrow service."""
    return EscrowService(db)
