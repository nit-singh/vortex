"""Pydantic models for KYC verification."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class Gender(str, Enum):
    MALE = "Male"
    FEMALE = "Female"
    TRANSGENDER = "Transgender"
    OTHER = "Other"


class MaritalStatus(str, Enum):
    SINGLE = "Single"
    MARRIED = "Married"
    DIVORCED = "Divorced"
    WIDOWED = "Widowed"


class QuestionAnswer(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class PANCardInput(BaseModel):
    pan_number: Optional[str] = None
    name: Optional[str] = None
    father_name: Optional[str] = None
    dob: Optional[str] = None
    raw_text: Optional[str] = None


class AadhaarCardInput(BaseModel):
    aadhaar_number: Optional[str] = None
    name: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[Gender] = None


class ITRDocumentInput(BaseModel):
    PAN: Optional[str] = None
    Name: Optional[str] = None
    Status: Optional[str] = None
    ITR_Type: Optional[str] = None
    Filed_u_s: Optional[str] = None
    Total_Income: Optional[str] = None
    Taxes_Paid: Optional[str] = None


class QuestionnaireInput(BaseModel):
    Q1: Optional[QuestionAnswer] = None
    Q2: Optional[QuestionAnswer] = None
    Q3: Optional[QuestionAnswer] = None
    Q4: Optional[QuestionAnswer] = None
    Q5: Optional[QuestionAnswer] = None
    Q6: Optional[QuestionAnswer] = None


class AdditionalDetails(BaseModel):
    amount_to_invest: Optional[float] = None
    address: Optional[str] = None
    main_occupation: Optional[str] = None
    marital_status: Optional[MaritalStatus] = None
    dependents: Optional[int] = None
    citizenship: Optional[str] = None

