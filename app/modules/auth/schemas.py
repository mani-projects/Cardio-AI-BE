from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    # Length is enforced here; the character-class requirement (uppercase +
    # a digit/symbol) mirrors the checklist shown on the signup form.
    password: str = Field(min_length=8, max_length=72, pattern=r"^(?=.*[A-Z])(?=.*[\d\W]).*$")
    full_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class RefreshRequest(BaseModel):
    refresh_token: str


class VerifyOtpRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
