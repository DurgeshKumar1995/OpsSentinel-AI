from pydantic import BaseModel, Field


class LogCheckInput(BaseModel):
    service_name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
        description="DNS-style service identifier",
    )
    window_minutes: int = Field(
        gt=0, le=120, description="Log lookback window in minutes (1-120)"
    )


class RestartServiceInput(BaseModel):
    service_name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
        description="DNS-style service identifier",
    )
    reason: str = Field(
        min_length=5, max_length=500, description="Detailed reason for restarting the service"
    )
