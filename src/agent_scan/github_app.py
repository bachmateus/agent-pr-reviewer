"""Auth via GitHub App: JWT RS256 -> installation token efêmero (~1h).
Sem PAT, sem rotação manual."""
import time

from agent_scan.pr import _API, http


def mint_installation_token(app_id: str, installation_id: str,
                            private_key_pem: str) -> str:
    import jwt  # PyJWT
    iat = int(time.time()) - 60  # tolera clock skew
    app_jwt = jwt.encode(
        {"iat": iat, "exp": iat + 600, "iss": str(app_id)},
        private_key_pem, algorithm="RS256")
    status, body = http("POST",
        f"{_API}/app/installations/{installation_id}/access_tokens", app_jwt)
    if status >= 400:
        raise RuntimeError(
            f"GitHub App: mint do installation token falhou (HTTP {status}): {body}")
    return body["token"]
