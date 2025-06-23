from typing import Any, Dict

from .gemini_provider import GeminiProvider


class VertexAIProvider(GeminiProvider):
    """Vertex AI provider implementation based on google-genai library"""

    def get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters"""
        # Initialize client params
        if not self.config.get("PROJECT") or not self.config.get("LOCATION"):
            raise ValueError("PROJECT and LOCATION are required for Vertex AI")
        return {
            "vertexai": True,
            "project": self.config.get("PROJECT"),
            "location": self.config.get("LOCATION"),
        }
