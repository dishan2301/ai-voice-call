import pytest
from starlette.testclient import TestClient
from deploy.cloud_app import app
from deploy import browser_voice


def test_rejects_other_origin_and_bad_access_code(monkeypatch):
    monkeypatch.setenv('VOICE_PREVIEW_TOKEN','synthetic-private-code')
    client=TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect('/talk/ws',headers={'origin':'https://evil.example'}):pass
    with client.websocket_connect('/talk/ws',headers={'origin':'https://testserver'}) as ws:
        ws.send_json({'sample_rate':48000,'token':'incorrect'})
        assert ws.receive_json()['type']=='error'
    assert not browser_voice.active


def test_valid_code_starts_general_voice_without_mail_or_real_provider(monkeypatch):
    monkeypatch.setenv('VOICE_PREVIEW_TOKEN','synthetic-private-code')
    import asyncio
    class FakeLive:
        def __init__(self,*a):self.closed=False
        async def start(self):pass
        async def receive(self):await asyncio.Event().wait()
        async def audio(self,pcm):pass
        async def close(self):self.closed=True
    monkeypatch.setattr(browser_voice,'OutlookConversationLive',FakeLive)
    with TestClient(app).websocket_connect('/talk/ws',headers={'origin':'https://testserver'}) as ws:
        ws.send_json({'sample_rate':48000,'token':'synthetic-private-code'})
        result=ws.receive_json()
        assert result['type']=='ready' and result['mail_connected'] is False
        ws.send_text('stop')
    assert not browser_voice.active


def test_phone_call_page_loads_without_private_configuration():
    response=TestClient(app).get('/talk')
    assert response.status_code==200
    assert 'type="password"' in response.text


def test_owned_google_session_starts_gmail_voice(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    context = SimpleNamespace(provider="gmail", legacy_local=False, session_id="owned")
    seen = []

    async def owner(*args):
        return context

    class FakeGmail:
        def __init__(self, settings, voice, emit, clear, mailbox):
            seen.append(mailbox)
        async def start(self): pass
        async def receive(self): await asyncio.Event().wait()
        async def close(self): pass

    monkeypatch.setattr(browser_voice, "require_mailbox_context", owner)
    monkeypatch.setattr(browser_voice, "HostedGmailLive", FakeGmail)
    with TestClient(app).websocket_connect("/talk/ws", headers={
        "origin": "https://testserver", "cookie": "morning_mail_session=synthetic"
    }) as ws:
        ws.send_json({"sample_rate": 48000})
        assert ws.receive_json()["mail_connected"] is True
        ws.send_text("stop")
    assert seen == [context]
    assert not browser_voice.active


def test_hosted_metadata_uses_only_individual_authorized_gets():
    from unittest.mock import Mock
    from app.email.gmail import GmailProvider

    service = Mock()
    service._http.supports_batch = False
    api = service.users.return_value.messages.return_value
    api.list.return_value.execute.return_value = {"messages": [{"id": "example"}]}
    api.get.return_value.execute.return_value = {"internalDate": "1780000000000"}
    assert GmailProvider(service).search_metadata("", 5, inbox=True)["messages"][0]["id"] == "example"
    assert api.get.call_args.kwargs["format"] == "metadata"
    service.new_batch_http_request.assert_not_called()
