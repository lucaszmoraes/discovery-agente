import os
import requests


def upload_pdf_to_slack(pdf_bytes: bytes, filename: str, channel_id: str, message: str) -> bool:
    token = os.environ.get("SLACK_BOT_TOKEN")

    response = requests.post(
        "https://slack.com/api/files.getUploadURLExternal",
        headers={"Authorization": f"Bearer {token}"},
        data={"filename": filename, "length": len(pdf_bytes)}
    )
    data = response.json()
    if not data.get("ok"):
        return False

    upload_url = data["upload_url"]
    file_id = data["file_id"]

    requests.post(
        upload_url,
        data=pdf_bytes,
        headers={"Content-Type": "application/octet-stream"}
    )

    complete_response = requests.post(
        "https://slack.com/api/files.completeUploadExternal",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "files": [{"id": file_id}],
            "channel_id": channel_id,
            "initial_comment": message
        }
    )
    return complete_response.json().get("ok", False)


def post_message_to_slack(channel_id: str, message: str) -> bool:
    token = os.environ.get("SLACK_BOT_TOKEN")
    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": channel_id, "text": message}
    )
    return response.json().get("ok", False)