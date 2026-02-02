"""Authentication API routes."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company
from app.schemas import CompanyRegister, CompanyLogin, Token, CompanyOut, DepositRequest
from app.services.auth import (
    hash_password, verify_password, create_access_token, get_current_company
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token)
def register(data: CompanyRegister, db: Session = Depends(get_db)):
    """Register a new company account."""
    # Check if email exists
    existing = db.query(Company).filter(Company.email == data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create company
    company = Company(
        email=data.email,
        password_hash=hash_password(data.password),
        name=data.name,
        description=data.description,
        balance=1000.0,  # Starting balance for demo
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    # Create token
    token = create_access_token({"sub": str(company.id)})
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(data: CompanyLogin, db: Session = Depends(get_db)):
    """Login and get access token."""
    company = db.query(Company).filter(Company.email == data.email).first()

    if not company or not verify_password(data.password, company.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    if not company.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated"
        )

    # Update last login
    company.last_login_at = datetime.utcnow()
    db.commit()

    token = create_access_token({"sub": str(company.id)})
    return Token(access_token=token)


@router.get("/me", response_model=CompanyOut)
def get_me(company: Company = Depends(get_current_company)):
    """Get current company info."""
    return company


@router.post("/deposit")
def deposit(
    data: DepositRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Add funds to company balance (simulated)."""
    company.balance += data.amount
    db.commit()
    return {"message": f"Deposited ${data.amount:.2f}", "new_balance": company.balance}
