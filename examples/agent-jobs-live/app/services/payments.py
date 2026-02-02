"""Payment services - Stripe and Crypto integrations."""
from datetime import datetime
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Company, AgentNode, PaymentTransaction


class StripePaymentService:
    """
    Stripe payment integration.

    In production, this would use the real Stripe SDK:
    - stripe.checkout.Session.create() for deposits
    - stripe.Transfer.create() for payouts to connected accounts
    """

    def __init__(self, db: Session):
        self.db = db
        self.is_live = bool(settings.stripe_secret_key and not settings.stripe_secret_key.startswith("sk_test"))

    def create_checkout_session(
        self,
        company: Company,
        amount: float,
        success_url: str,
        cancel_url: str
    ) -> dict:
        """
        Create a Stripe Checkout session for company to add funds.

        In production:
            import stripe
            stripe.api_key = settings.stripe_secret_key
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {'name': 'Account Deposit'},
                        'unit_amount': int(amount * 100),
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={'company_id': company.id},
            )
            return {"checkout_url": session.url, "session_id": session.id}
        """
        if settings.payment_mode == "simulated":
            # Simulated: just add funds directly
            company.balance += amount
            self.db.commit()
            return {
                "checkout_url": f"{success_url}?simulated=true&amount={amount}",
                "session_id": f"sim_{company.id}_{int(datetime.utcnow().timestamp())}",
                "simulated": True,
                "message": f"Simulated: ${amount:.2f} added to balance"
            }

        # Would integrate real Stripe here
        raise NotImplementedError("Real Stripe integration requires STRIPE_SECRET_KEY")

    def handle_webhook(self, payload: dict, signature: str) -> bool:
        """
        Handle Stripe webhook for payment confirmation.

        In production:
            event = stripe.Webhook.construct_event(
                payload, signature, settings.stripe_webhook_secret
            )
            if event['type'] == 'checkout.session.completed':
                session = event['data']['object']
                company_id = session['metadata']['company_id']
                amount = session['amount_total'] / 100
                # Credit company balance
        """
        return True

    def create_payout(self, agent: AgentNode, amount: float) -> dict:
        """
        Create payout to agent's Stripe connected account.

        In production:
            transfer = stripe.Transfer.create(
                amount=int(amount * 100),
                currency='usd',
                destination=agent.stripe_account_id,
            )
        """
        if settings.payment_mode == "simulated":
            if amount > agent.pending_payout:
                raise ValueError(f"Insufficient balance: ${agent.pending_payout:.2f} available")

            agent.pending_payout -= amount
            self.db.commit()

            return {
                "payout_id": f"sim_payout_{agent.id}_{int(datetime.utcnow().timestamp())}",
                "amount": amount,
                "status": "completed",
                "simulated": True,
            }

        raise NotImplementedError("Real Stripe payouts require configuration")


class CryptoPaymentService:
    """
    Crypto payment integration.

    For production, would integrate with:
    - Circle (USDC): https://developers.circle.com/
    - Coinbase Commerce: https://commerce.coinbase.com/
    - Or direct Web3 integration with ethers.js
    """

    def __init__(self, db: Session):
        self.db = db
        # Platform wallet addresses (would be from env in production)
        self.deposit_addresses = {
            "ethereum": "0x742d35Cc6634C0532925a3b844Bc9e7595f8fE00",  # Example
            "polygon": "0x742d35Cc6634C0532925a3b844Bc9e7595f8fE00",
            "arbitrum": "0x742d35Cc6634C0532925a3b844Bc9e7595f8fE00",
        }
        self.accepted_tokens = ["USDC", "USDT", "ETH"]

    def get_deposit_info(self, company: Company, network: str = "ethereum") -> dict:
        """
        Get deposit address for company to send crypto.

        In production, would generate unique deposit address per company
        using HD wallets or Circle's API.
        """
        if network not in self.deposit_addresses:
            raise ValueError(f"Unsupported network: {network}")

        return {
            "deposit_address": self.deposit_addresses[network],
            "network": network,
            "accepted_tokens": self.accepted_tokens,
            "min_amount": 10.0,  # Minimum $10 deposit
            "company_reference": f"COMP-{company.id}",  # Include in memo/data
            "instructions": f"Send USDC/USDT/ETH to the address above. Include 'COMP-{company.id}' in the transaction data or memo for automatic credit.",
        }

    def verify_deposit(self, tx_hash: str, network: str) -> dict | None:
        """
        Verify a crypto deposit transaction.

        In production:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(RPC_URL))
            tx = w3.eth.get_transaction(tx_hash)
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            # Parse token transfer, verify amount, credit company
        """
        if settings.payment_mode == "simulated":
            return {
                "verified": True,
                "amount": 100.0,  # Simulated amount
                "token": "USDC",
                "network": network,
                "simulated": True,
            }

        raise NotImplementedError("Real crypto verification requires Web3 integration")

    def create_payout(
        self,
        agent: AgentNode,
        amount: float,
        wallet_address: str,
        token: str = "USDC",
        network: str = "ethereum"
    ) -> dict:
        """
        Send crypto payout to agent's wallet.

        In production:
            # Using Circle API for USDC:
            transfer = circle_client.transfers.create(
                destination={"type": "blockchain", "address": wallet_address, "chain": network},
                amount={"amount": str(amount), "currency": "USD"},
            )

            # Or direct Web3:
            tx = token_contract.functions.transfer(wallet_address, amount_wei).build_transaction({...})
            signed = w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        """
        if amount > agent.pending_payout:
            raise ValueError(f"Insufficient balance: ${agent.pending_payout:.2f} available")

        if token not in self.accepted_tokens:
            raise ValueError(f"Unsupported token: {token}")

        if settings.payment_mode == "simulated":
            agent.pending_payout -= amount
            self.db.commit()

            return {
                "payout_id": f"sim_crypto_{agent.id}_{int(datetime.utcnow().timestamp())}",
                "amount": amount,
                "token": token,
                "network": network,
                "wallet_address": wallet_address,
                "tx_hash": f"0x{'0' * 64}",  # Simulated tx hash
                "status": "completed",
                "simulated": True,
            }

        raise NotImplementedError("Real crypto payouts require Web3 integration")

    def estimate_gas(self, network: str, token: str) -> dict:
        """Estimate gas fees for a payout."""
        # Simulated gas estimates
        gas_prices = {
            "ethereum": {"USDC": 5.0, "USDT": 5.0, "ETH": 3.0},
            "polygon": {"USDC": 0.01, "USDT": 0.01, "ETH": 0.01},
            "arbitrum": {"USDC": 0.10, "USDT": 0.10, "ETH": 0.05},
        }

        return {
            "network": network,
            "token": token,
            "estimated_fee_usd": gas_prices.get(network, {}).get(token, 1.0),
            "note": "Fee deducted from payout amount",
        }


def get_stripe_service(db: Session) -> StripePaymentService:
    return StripePaymentService(db)


def get_crypto_service(db: Session) -> CryptoPaymentService:
    return CryptoPaymentService(db)
