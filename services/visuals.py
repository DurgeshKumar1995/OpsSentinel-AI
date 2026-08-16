"""Generate safe visual companions for DevOps text answers."""

import base64
from pathlib import Path
from uuid import uuid4

from openai import OpenAI

from config.settings import Settings


class VisualGenerator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.output_dir = Path(settings.generated_image_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    @property
    def available(self) -> bool:
        return self.settings.image_generation_enabled and self.client is not None

    def generate(self, request: str, answer: str) -> str:
        if not self.available:
            raise RuntimeError("Image generation is not configured")
        prompt = (
            "Create a clean professional landscape DevOps architecture diagram. "
            "Use a light background, dark green and muted blue components, clear arrows, "
            "short readable labels, and generous spacing. Show only systems and flow "
            "supported by the request and answer. Do not include secrets, credentials, "
            "company logos, or claims that an action ran. "
            f"User request: {request}\nApproved text explanation: {answer[:2500]}"
        )
        result = self.client.images.generate(
            model=self.settings.image_model,
            prompt=prompt,
            size=self.settings.image_size,
            quality=self.settings.image_quality,
        )
        encoded = result.data[0].b64_json
        if not encoded:
            raise RuntimeError("Image model returned no image data")
        filename = f"devops-visual-{uuid4().hex}.png"
        (self.output_dir / filename).write_bytes(base64.b64decode(encoded))
        return f"/generated/{filename}"
