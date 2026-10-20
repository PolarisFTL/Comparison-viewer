"""Validation of private, machine-local configuration; never changes images."""
import os
import re
import stat
import unicodedata
import uuid
from pathlib import Path

METHOD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _text(value, label, maximum):
    if not isinstance(value, str):
        raise ValueError("{} must be text".format(label))
    value = value.strip()
    if not value or len(value) > maximum:
        raise ValueError("{} must contain 1–{} characters".format(label, maximum))
    if any(unicodedata.category(ch).startswith("C") for ch in value):
        raise ValueError("{} must not contain control characters".format(label))
    return value


def _directory(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Each method requires an absolute directory path")
    if "\x00" in value:
        raise ValueError("Directory path contains a NUL character")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Directory path must be absolute: {}".format(value))
    # Reject a selected link/junction itself, then canonicalize ancestors. macOS
    # intentionally links system parents such as /var and /tmp to /private.
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError("Directory cannot be accessed: {} ({})".format(path, exc))
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Symbolic links/junctions are not accepted: {}".format(path))
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Directory cannot be accessed: {} ({})".format(path, exc))
    if path.parent == path or os.path.ismount(str(path)):
        raise ValueError("Selecting an entire disk/filesystem root is not allowed")
    if not path.is_dir():
        raise ValueError("Image directory does not exist: {}".format(path))
    return str(path)


def normalize_config(data):
    """Return validated schema-2 metadata. Stable IDs are supplied by setup UI."""
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data.get("schema") != 2:
        raise ValueError("Configuration schema must be 2")
    dataset = _text(data.get("dataset"), "Dataset name", 100)
    raw_id = data.get("datasetId")
    if not isinstance(raw_id, str):
        raise ValueError("datasetId must be a persistent UUID")
    try:
        dataset_id = str(uuid.UUID(raw_id))
    except (ValueError, AttributeError):
        raise ValueError("datasetId must be a persistent UUID")
    raw_methods = data.get("methods")
    if not isinstance(raw_methods, list) or not 2 <= len(raw_methods) <= 24:
        raise ValueError("Choose between 2 and 24 method directories")
    methods, seen = [], set()
    for index, raw in enumerate(raw_methods):
        if not isinstance(raw, dict):
            raise ValueError("Method {} is not an object".format(index + 1))
        method_id = raw.get("id")
        if not isinstance(method_id, str) or not METHOD_ID.fullmatch(method_id):
            raise ValueError("Method IDs must contain 1–64 ASCII letters, digits, - or _")
        if method_id in seen:
            raise ValueError("Method IDs must be unique: {}".format(method_id))
        seen.add(method_id)
        methods.append({"id": method_id, "name": _text(raw.get("name"), "Method name", 60),
                        "root": _directory(raw.get("root"))})
    reference_id = data.get("referenceId")
    if not isinstance(reference_id, str) or reference_id not in seen:
        raise ValueError("referenceId must identify one of the selected methods")
    return {"schema": 2, "dataset": dataset, "datasetId": dataset_id,
            "referenceId": reference_id, "methods": methods}
