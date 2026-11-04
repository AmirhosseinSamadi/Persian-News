"""Value-free Bale shape diagnostics; never echo arbitrary keys or payload values."""

SERVICE_FIELDS = (
    "new_chat_members",
    "left_chat_member",
    "new_chat_title",
    "new_chat_photo",
    "delete_chat_photo",
    "group_chat_created",
    "supergroup_chat_created",
    "channel_chat_created",
    "pinned_message",
    "web_app_data",
    "successful_payment",
)
MEDIA_FIELDS = (
    "photo",
    "video",
    "animation",
    "audio",
    "voice",
    "document",
    "sticker",
    "contact",
    "location",
    "video_note",
)
KNOWN_FIELDS = frozenset(
    SERVICE_FIELDS
    + MEDIA_FIELDS
    + (
        "message_id",
        "date",
        "chat",
        "text",
        "caption",
        "from",
        "sender_chat",
        "edit_date",
        "entities",
        "caption_entities",
        "reply_markup",
        "reply_to_message",
    )
)


def _kind(value):
    if value is None:
        return "null"
    return {
        bool: "boolean",
        int: "integer",
        float: "number",
        str: "string",
        list: "array",
        dict: "object",
    }.get(type(value), "unsupported_type")


def classify_membership(message, event_type):
    """Recognize one Bale service envelope without creating a news record."""
    if not isinstance(message, dict) or "new_chat_members" not in message:
        return "not_membership_service"
    try:
        if event_type != "message":
            raise ValueError
        if {key for key in SERVICE_FIELDS if key in message} != {"new_chat_members"}:
            raise ValueError
        if any(
            message.get(key) is not None for key in MEDIA_FIELDS + ("text", "caption")
        ):
            raise ValueError
        for key in ("message_id", "date"):
            if type(message.get(key)) is not int or message[key] < 0:
                raise ValueError
        chat = message["chat"]
        if type(chat.get("id")) is not int or chat.get("type") not in (
            "group",
            "channel",
        ):
            raise ValueError
        members = message["new_chat_members"]
        if not isinstance(members, list) or not members:
            raise ValueError
        for member in members:
            if not isinstance(member, dict) or type(member.get("is_bot")) is not bool:
                raise ValueError
            if "id" in member and (type(member["id"]) is not int or member["id"] <= 0):
                raise ValueError
            for key in ("first_name", "last_name", "username", "language_code"):
                if key == "first_name" or key in member:
                    if not isinstance(member.get(key), str):
                        raise ValueError
                    member[key].encode("utf-8")
        return (
            "membership_group"
            if chat["type"] == "group"
            else "membership_channel_review"
        )
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        return "invalid_membership_service"


def diagnose_update(update):
    """Describe known field names/types only; acknowledgement policy is separate."""
    result = {
        "event_type": "unsupported",
        "chat_type": None,
        "variant": "unknown",
        "known_field_types": {},
        "issues": [],
        "unknown_message_field_count": 0,
    }

    def issue(field, code, actual_type):
        result["issues"].append(
            {"field": field, "code": code, "actual_type": actual_type}
        )

    def required_integer(container, key, path, minimum=None):
        if key not in container:
            issue(path, "missing_required_field", "missing")
        elif type(container[key]) is not int:
            issue(path, "expected_integer", _kind(container[key]))
        elif minimum is not None and container[key] < minimum:
            code = "zero_not_supported" if container[key] == 0 else "below_minimum"
            issue(path, code, "integer")

    if not isinstance(update, dict):
        issue("update", "expected_object", _kind(update))
        return result
    required_integer(update, "update_id", "update.update_id", 0)
    fields = set(update) - {"update_id"}
    known = fields & {
        "message",
        "edited_message",
        "callback_query",
        "pre_checkout_query",
    }
    if len(fields) != 1 or len(known) != 1:
        issue("update", "unsupported_envelope_fields", "object")
        return result
    event = known.pop()
    result["event_type"] = event
    if event not in {"message", "edited_message"}:
        issue("update", "unsupported_event_variant", "object")
        return result
    message = update[event]
    if not isinstance(message, dict):
        issue("message", "expected_object", _kind(message))
        return result
    result["known_field_types"] = {
        key: _kind(message[key]) for key in sorted(KNOWN_FIELDS & message.keys())
    }
    result["unknown_message_field_count"] = len(set(message) - KNOWN_FIELDS)
    service = [field for field in SERVICE_FIELDS if field in message]
    media = [field for field in MEDIA_FIELDS if field in message]
    result["variant"] = (
        "service_candidate"
        if service
        else "text"
        if "text" in message
        else "caption"
        if "caption" in message
        else "media"
        if media
        else "textless"
    )
    result["service_fields_present"] = service
    result["media_fields_present"] = media
    classification = classify_membership(message, event)
    result["service_classification"] = classification
    recognized = classification in {"membership_group", "membership_channel_review"}
    required_integer(
        message, "message_id", "message.message_id", 0 if recognized else 1
    )
    if classification == "invalid_membership_service":
        issue(
            "message.new_chat_members",
            "invalid_or_ambiguous_service_structure",
            "object",
        )
    required_integer(message, "date", "message.date", 0)
    if "chat" not in message:
        issue("message.chat", "missing_required_field", "missing")
    elif not isinstance(message["chat"], dict):
        issue("message.chat", "expected_object", _kind(message["chat"]))
    else:
        chat = message["chat"]
        required_integer(chat, "id", "message.chat.id")
        kind = chat.get("type")
        if kind in ("private", "group", "channel"):
            result["chat_type"] = kind
        else:
            issue(
                "message.chat.type",
                "unsupported_chat_type",
                _kind(kind) if "type" in chat else "missing",
            )
    for field in ("text", "caption"):
        value = message.get(field)
        if value is not None and not isinstance(value, str):
            issue("message." + field, "expected_optional_string", _kind(value))
        elif isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeError:
                issue("message." + field, "invalid_unicode", "string")
    if "new_chat_members" in message:
        members = message["new_chat_members"]
        result["service_support"] = (
            "documented_group_membership"
            if result["chat_type"] == "group"
            else "observed_scope_not_documented"
        )
        if not isinstance(members, list) or not all(
            isinstance(m, dict) for m in members
        ):
            issue(
                "message.new_chat_members", "expected_array_of_objects", _kind(members)
            )
        if result["chat_type"] != "group":
            issue(
                "message.new_chat_members",
                "service_scope_not_documented",
                _kind(members),
            )
    return result
