from __future__ import annotations

from dataclasses import dataclass

import httpx
import msal


class OboExchangeError(Exception):
    pass


@dataclass(frozen=True)
class ResolvedIdentity:
    upn: str
    display_name: str
    object_id: str


class GraphOboResolver:
    GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"
    GRAPH_SCOPE = ["https://graph.microsoft.com/User.Read"]

    def __init__(self, msal_app, http_client: httpx.Client | None = None):
        self._msal_app = msal_app
        self._http_client = http_client or httpx.Client(timeout=10.0)

    def resolve(self, user_access_token: str) -> ResolvedIdentity:
        result = self._msal_app.acquire_token_on_behalf_of(
            user_assertion=user_access_token,
            scopes=self.GRAPH_SCOPE,
        )
        if "access_token" not in result:
            raise OboExchangeError(result.get("error_description", "OBO token exchange failed"))

        graph_token = result["access_token"]
        response = self._http_client.get(
            self.GRAPH_ME_URL,
            headers={"Authorization": f"Bearer {graph_token}"},
        )
        if response.status_code != 200:
            raise OboExchangeError(f"Graph /me call failed: {response.status_code} {response.text}")

        data = response.json()
        upn = data.get("userPrincipalName") or data.get("mail")
        if not upn:
            raise OboExchangeError("Graph /me response missing userPrincipalName/mail")

        return ResolvedIdentity(
            upn=upn,
            display_name=data.get("displayName", ""),
            object_id=data.get("id", ""),
        )


def build_msal_confidential_app(tenant_id: str, client_id: str, client_secret: str) -> msal.ConfidentialClientApplication:
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )
