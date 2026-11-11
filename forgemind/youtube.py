from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

UPLOAD_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
SERVICE = "ForgeMind.YouTube"
ACCOUNT = "desktop-upload"


class YouTubePublisher:
    """OAuth tokens live in the OS credential store, outside indexed knowledge."""

    def connected(self) -> bool:
        import keyring
        return bool(keyring.get_password(SERVICE, ACCOUNT))

    def connect(self, client_file: Path) -> None:
        import keyring
        from google_auth_oauthlib.flow import InstalledAppFlow

        config = json.loads(Path(client_file).read_text(encoding="utf-8"))
        if "installed" not in config:
            raise ValueError("Download an OAuth client of type Desktop app from Google Cloud.")
        flow = InstalledAppFlow.from_client_config(config, UPLOAD_SCOPES)
        credentials = flow.run_local_server(port=0, timeout_seconds=180,
                                            access_type="offline", prompt="consent")
        keyring.set_password(SERVICE, ACCOUNT, credentials.to_json())

    def disconnect(self) -> None:
        import keyring
        if self.connected():
            keyring.delete_password(SERVICE, ACCOUNT)

    def _credentials(self):
        import keyring
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        saved = keyring.get_password(SERVICE, ACCOUNT)
        if not saved:
            raise RuntimeError("Connect your YouTube account first.")
        credentials = Credentials.from_authorized_user_info(json.loads(saved), UPLOAD_SCOPES)
        if not credentials.valid:
            if not credentials.refresh_token:
                raise RuntimeError("Reconnect YouTube to renew its upload permission.")
            credentials.refresh(Request())
            keyring.set_password(SERVICE, ACCOUNT, credentials.to_json())
        return credentials

    def upload(self, path: Path, title: str, description: str = "", privacy: str = "private",
               made_for_kids: bool = False, progress: Callable | None = None) -> dict:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        if privacy not in {"private", "unlisted", "public"}:
            raise ValueError("Choose private, unlisted, or public visibility.")
        if not title.strip() or len(title.strip()) > 100:
            raise ValueError("YouTube titles must be between 1 and 100 characters.")
        if not Path(path).is_file():
            raise FileNotFoundError("Render the selected clip before uploading it.")
        service = build("youtube", "v3", credentials=self._credentials(), cache_discovery=False)
        try:
            request = service.videos().insert(
                part="snippet,status",
                body={"snippet": {"title": title.strip(), "description": description, "categoryId": "22"},
                      "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids}},
                media_body=MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024,
                                          resumable=True),
            )
            response = None
            while response is None:
                status, response = request.next_chunk(num_retries=3)
                if status and progress:
                    progress(f"Uploading to YouTube: {status.progress() * 100:.0f}%")
            identifier = response.get("id")
            if not identifier:
                raise RuntimeError("YouTube returned no video ID. Check YouTube Studio before retrying.")
            return {"video_id": identifier, "url": f"https://www.youtube.com/watch?v={identifier}",
                    "privacy": response.get("status", {}).get("privacyStatus", privacy)}
        finally:
            service.close()
