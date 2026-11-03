
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = BACKEND_ROOT / ".env"
DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

load_dotenv(ENV_PATH)


class Settings:
    def __init__(self) -> None:
        self.app_name = "AnchorCV API"
        self.api_prefix = "/api"

        # Existing LLM providers
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")

        # Otari gateway configuration
        self.otari_api_key = os.getenv("OTARI_API_KEY", "")
        self.otari_base_url = os.getenv(
            "OTARI_BASE_URL",
            "https://otari.ai/api/v1",
        ).rstrip("/")

        self.llm_provider = os.getenv(
            "LLM_PROVIDER",
            "native",
        ).strip().lower()

        if self.llm_provider not in {"native", "otari"}:
            raise ValueError(
                "LLM_PROVIDER must be either 'native' or 'otari'."
            )

        # Otari model roles. Each value is an Otari routing policy name
        # (created in the Otari dashboard, with fallbacks) or a plain model id.
        # Defaults are open-weight models so the app works before policies exist.
        self.otari_model_fast = os.getenv(
            "OTARI_MODEL_FAST", "openai/gpt-oss-20b"
        ).strip()
        self.otari_model_strong = os.getenv(
            "OTARI_MODEL_STRONG", "openai/gpt-oss-120b"
        ).strip()
        self.otari_model_guard = os.getenv(
            "OTARI_MODEL_GUARD", "openai/gpt-oss-safeguard-120b"
        ).strip()

        # Per-user budgets: an Otari *service key* bills each AnchorCV user as
        # an Otari end user with their own budget. Without it, every request is
        # billed to OTARI_API_KEY's own user.
        self.otari_service_key = os.getenv("OTARI_SERVICE_KEY", "").strip()
        self.otari_budget_trial = os.getenv(
            "OTARI_END_USER_BUDGET_TRIAL", "anchorcv-trial"
        ).strip()
        self.otari_budget_premium = os.getenv(
            "OTARI_END_USER_BUDGET_PREMIUM", "anchorcv-season-pass"
        ).strip()

        # Guardrails: Otari calls this AnchorCV endpoint before the model runs.
        # It must be a public https URL, e.g.
        # https://app.anchorcv.com/api/guardrails/<OTARI_GUARDRAIL_TOKEN>
        self.otari_guardrail_url = os.getenv(
            "OTARI_GUARDRAIL_URL", ""
        ).strip().rstrip("/")
        self.otari_guardrail_token = os.getenv(
            "OTARI_GUARDRAIL_TOKEN", ""
        ).strip()
        self.otari_guardrail_profile = os.getenv(
            "OTARI_GUARDRAIL_PROFILE", "anchorcv-integrity"
        ).strip()

        # Database
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_service_key = os.getenv("SUPABASE_SERVICE_KEY", "")

        # Session
        self.session_cookie_name = os.getenv(
            "ANCHORCV_SESSION_COOKIE", "anchorcv_session"
        )
        self.session_secret = os.getenv(
            "ANCHORCV_SESSION_SECRET", "change-me-in-production"
        )
        self.session_max_age = int(
            os.getenv("ANCHORCV_SESSION_MAX_AGE", str(7 * 24 * 3600))
        )
        self.secure_cookies = (
            os.getenv("ANCHORCV_SECURE_COOKIES", "false").lower() == "true"
        )

        self.allowed_origins = [
            origin.strip()
            for origin in os.getenv(
                "ANCHORCV_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS
            ).split(",")
            if origin.strip()
        ]

        # Search providers
        self.google_search_api_key = os.getenv("GOOGLE_SEARCH_API_KEY", "")
        self.google_search_cx = os.getenv("GOOGLE_SEARCH_CX", "")
        self.adzuna_app_id = os.getenv("ADZUNA_APP_ID", "")
        self.adzuna_api_key = os.getenv("ADZUNA_API_KEY", "")
        self.serper_api_key = os.getenv("SERPER_API_KEY", "")

        # Application
        self.app_url = os.getenv("APP_URL", "http://localhost:5173")
        self.lemon_checkout_url = os.getenv(
            "LEMONSQUEEZY_CHECKOUT_URL",
            "https://anchorcv.lemonsqueezy.com/checkout/buy/e4843985-0685-4fc2-8aa7-2e2f03d28700",
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
