"""Konfigurasi dari environment. Gagal-cepat bila setelan tidak aman di production."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def _bool(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


class Settings:
    def __init__(self) -> None:
        self.env = os.getenv("APP_ENV", "development")
        self.is_prod = self.env == "production"
        self.database_url = os.getenv("DATABASE_URL", "")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL wajib diisi; konfigurasi aplikasi tidak lagi memakai SQLite lokal.")
        if self.database_url.startswith("sqlite") and os.getenv("APP_ENV") != "test":
            raise RuntimeError("SQLite hanya boleh digunakan oleh database tes; gunakan PostgreSQL untuk aplikasi.")
        self.jwt_secret = os.getenv("JWT_SECRET", "")
        self.jwt_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
        self.cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
        self.public_app_url = os.getenv("PUBLIC_APP_URL", "http://localhost:8000").rstrip("/")
        # Pilih chain hanya lewat .env: mock untuk simulasi, web3 untuk Sepolia.
        # Ubah nilai CHAIN_MODE dan restart backend; jangan aktifkan dua implementasi
        # sekaligus atau mengedit get_chain() saat berpindah jaringan.
        self.chain_mode = os.getenv("CHAIN_MODE", "mock")  # mock | web3
        self.mock_chain_file = os.getenv("MOCK_CHAIN_FILE", ".mockchain.json")
        self.rpc_url = os.getenv("RPC_URL", "")
        self.contract_address = os.getenv("CONTRACT_ADDRESS", "")
        self.chain_private_key = os.getenv("CHAIN_PRIVATE_KEY", "")  # akun testnet saja
        self.chain_id = int(os.getenv("CHAIN_ID", "11155111"))
        self.chain_name = os.getenv("CHAIN_NAME", "Sepolia")
        self.explorer_tx_base = os.getenv("BLOCK_EXPLORER_TX_BASE", "https://sepolia.etherscan.io/tx/")
        self.enable_tamper_sim = _bool("ENABLE_TAMPER_SIM")
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_from = os.getenv("SMTP_FROM", self.smtp_user)
        self.smtp_use_tls = _bool("SMTP_USE_TLS") if "SMTP_USE_TLS" in os.environ else True
        self.google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        self.enable_email_otp_registration = _bool("ENABLE_EMAIL_OTP_REGISTRATION")

        if not self.jwt_secret:
            if self.is_prod:
                raise RuntimeError("JWT_SECRET wajib diisi di production")
            self.jwt_secret = secrets.token_urlsafe(48)  # sementara, token mati saat restart
        self.otp_secret = os.getenv("OTP_SECRET", "") or self.jwt_secret
        if self.is_prod and len(self.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET minimal 32 karakter")
        if self.is_prod and self.enable_tamper_sim:
            raise RuntimeError("ENABLE_TAMPER_SIM tidak boleh aktif di production")
        if self.chain_mode not in ("mock", "web3"):
            raise RuntimeError("CHAIN_MODE harus 'mock' atau 'web3'")
        if self.chain_mode == "web3" and not (self.rpc_url and self.contract_address and self.chain_private_key):
            raise RuntimeError("CHAIN_MODE=web3 butuh RPC_URL, CONTRACT_ADDRESS, CHAIN_PRIVATE_KEY")


settings = Settings()
