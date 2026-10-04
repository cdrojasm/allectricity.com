from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenInput(Input):
    token: str = Field(min_length=16, max_length=12000)


class RefreshInput(Input):
    refresh_token: str = Field(min_length=16, max_length=128)


class RevokeInput(Input):
    all_sessions: bool = False


class ForgotPassword(Input):
    email: EmailStr


class ResetPassword(TokenInput):
    password: str = Field(min_length=12, max_length=128)


class ChangePassword(Input):
    current_password: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=128)


class UserCreate(Input):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(default="", max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    locale: str = Field(default="es-CO", min_length=2, max_length=20)
    timezone: str = Field(default="America/Bogota", min_length=1, max_length=100)


class PatchInput(Input):
    @model_validator(mode="after")
    def reject_nulls(self):
        if any(
            getattr(self, k) is None and k != "phone" for k in self.model_fields_set
        ):
            raise ValueError("Explicit null is not allowed for these fields")
        return self


class UserUpdate(PatchInput):
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    locale: str | None = Field(default=None, min_length=2, max_length=20)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    active: bool | None = None


class ClientCreate(Input):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr


class ClientCredentials(Input):
    grant_type: str = Field(
        default="client_credentials", pattern="^client_credentials$"
    )
    client_id: str = Field(min_length=1, max_length=36)
    client_secret: str = Field(min_length=1, max_length=128)


class RoleInput(Input):
    name: str = Field(min_length=1, max_length=60, pattern="^[a-z][a-z0-9_]*$")
    description: str = Field(default="", max_length=255)
    permissions: list[str] = Field(default_factory=list, max_length=30)


class Assignment(Input):
    user_id: str = Field(min_length=1, max_length=36)
    role_id: str = Field(min_length=1, max_length=36)


class BudgetCreate(Input):
    user_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=120)
    total_tokens: int = Field(ge=0, le=10**15, strict=True)


class BudgetUpdate(PatchInput):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    total_tokens: int | None = Field(default=None, ge=0, le=10**15, strict=True)
    active: bool | None = None


class UsageInput(Input):
    input_tokens: int = Field(ge=0, le=10**12, strict=True)
    output_tokens: int = Field(ge=0, le=10**12, strict=True)
    project_id: str = Field(min_length=1, max_length=100, pattern=r"\S")
    action: str = Field(min_length=1, max_length=120, pattern=r"\S")
    model: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=128)
