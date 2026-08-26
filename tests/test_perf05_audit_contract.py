from pathlib import Path


WEBHOOK = Path(
    "app/routers/whatsapp_webhook.py"
)


def webhook_source() -> str:
    return WEBHOOK.read_text(
        encoding="utf-8",
    )


def test_perf_audit_has_required_dimensions():
    source = webhook_source()

    required = {
        '"event": "PERF_AUDIT"',
        '"request_id": _perf_request_id',
        '"message_type": message_type',
        '"sender_suffix": from_number[-4:]',
        '"tenant_s": 0.0',
        '"media_url_fetch_s": 0.0',
        '"media_download_s": 0.0',
        '"catalog_query_s": 0.0',
        '"transcription_s": 0.0',
        '"business_processing_s": 0.0',
        '"send_reply_s": 0.0',
        '"backend_total_s": 0.0',
    }

    for field in required:
        assert field in source


def test_perf_audit_is_json():
    source = webhook_source()

    assert '"PERF_AUDIT:"' in source
    assert "json.dumps(" in source
    assert "ensure_ascii=False" in source
    assert "sort_keys=True" in source


def test_request_id_uses_whatsapp_message_id():
    source = webhook_source()

    assert 'message.get("id")' in source
    assert 'f"local-{time.time_ns()}"' in source


def test_total_is_measured_after_reply_send():
    source = webhook_source()

    send_position = source.rfind(
        "send_whatsapp_text_message("
    )
    total_position = source.index(
        '_perf["backend_total_s"] = round('
    )

    assert total_position > send_position


def test_perf_payload_masks_sender():
    source = webhook_source()

    perf_start = source.index(
        "_perf = {"
    )
    perf_end = source.index(
        "\n                    }",
        perf_start,
    )
    payload = source[perf_start:perf_end]

    assert '"sender_suffix"' in payload
    assert '"from_number":' not in payload
    assert '"sender":' not in payload
