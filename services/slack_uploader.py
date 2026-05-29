import os
import requests


def upload_pdf_to_slack(pdf_bytes: bytes, filename: str, channel_id: str, message: str, thread_ts: str = None) -> bool:
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

    payload = {
        "files": [{"id": file_id}],
        "channel_id": channel_id,
        "initial_comment": message
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    complete_response = requests.post(
        "https://slack.com/api/files.completeUploadExternal",
        headers={"Authorization": f"Bearer {token}"},
        json=payload
    )
    return complete_response.json().get("ok", False)


def post_message_to_slack(channel_id: str, message: str, thread_ts: str = None) -> bool:
    token = os.environ.get("SLACK_BOT_TOKEN")

    payload = {"channel": channel_id, "text": message}
    if thread_ts:
        payload["thread_ts"] = thread_ts

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json=payload
    )
    return response.json().get("ok", False)