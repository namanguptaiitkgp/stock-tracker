from datetime import datetime

from pydantic import BaseModel, field_validator


VALID_CREDENTIAL_TYPES = {"gemini_api_key", "vertex_service_account"}

GCP_REGIONS = [
    "us-central1", "us-east1", "us-east4", "us-west1", "us-west4",
    "europe-west1", "europe-west2", "europe-west3", "europe-west4", "europe-west6",
    "asia-south1", "asia-southeast1", "asia-east1", "asia-northeast1",
    "australia-southeast1", "northamerica-northeast1", "southamerica-east1",
]


class AiCredentialCreate(BaseModel):
    credential_type: str
    label: str
    priority: int = 1
    is_active: bool = True
    default_model: str = "gemini-2.5-flash-lite"

    api_key: str | None = None

    project_id: str | None = None
    location: str | None = None
    client_email: str | None = None
    private_key_id: str | None = None
    private_key: str | None = None
    token_uri: str = "https://oauth2.googleapis.com/token"

    @field_validator("credential_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_CREDENTIAL_TYPES:
            raise ValueError(f"Must be one of: {', '.join(sorted(VALID_CREDENTIAL_TYPES))}")
        return v

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str | None) -> str | None:
        if v is not None and v not in GCP_REGIONS:
            raise ValueError(f"Unknown GCP region. Valid: {', '.join(GCP_REGIONS)}")
        return v


class AiCredentialUpdate(BaseModel):
    label: str | None = None
    priority: int | None = None
    is_active: bool | None = None
    default_model: str | None = None

    api_key: str | None = None

    project_id: str | None = None
    location: str | None = None
    client_email: str | None = None
    private_key_id: str | None = None
    private_key: str | None = None
    token_uri: str | None = None


class AiCredentialResponse(BaseModel):
    id: int
    credential_type: str
    label: str
    priority: int
    is_active: bool
    default_model: str

    api_key_masked: str | None = None

    project_id: str | None = None
    location: str | None = None
    client_email: str | None = None
    private_key_id: str | None = None
    private_key_configured: bool = False
    token_uri: str | None = None

    is_exhausted_today: bool = False

    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class AiCredentialStatusResponse(BaseModel):
    id: int
    label: str
    credential_type: str
    is_active: bool
    is_exhausted_today: bool
