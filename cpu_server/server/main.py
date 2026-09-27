import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile


app = FastAPI(title="Server")


ROOT = Path("/srv")
INCOMING_ROOT = ROOT / "incoming"
SESSION_ROOT = ROOT / "sessions"
LOCK_ROOT = ROOT / "locks"

MAX_METADATA_BYTES = 2 * 1024 * 1024

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


BASE_PARTS = {
    "metadata": "metadata.json",
    "main_video": "main_rgb.mp4",
    "main_frame_timestamps": "main_frame_timestamps.csv",
    "accelerometer": "accelerometer.csv",
    "gyroscope": "gyroscope.csv",
    "rotation_vector": "rotation_vector.csv",
    "arcore_poses": "arcore_poses.csv",
    "episodes": "episodes.csv",
}

ULTRAWIDE_PARTS = {
    "ultrawide_video": "ultrawide_rgb.mp4",
    "ultrawide_frame_timestamps":
        "ultrawide_frame_timestamps.csv",
}

CSV_HEADERS = {
    "main_frame_timestamps.csv":
        "frame_number,timestamp_ns,timestamp_source",

    "accelerometer.csv":
        "timestamp_ns,x,y,z,accuracy",

    "gyroscope.csv":
        "timestamp_ns,x,y,z,accuracy",

    "rotation_vector.csv":
        "timestamp_ns,x,y,z,scalar_component,"
        "heading_accuracy_rad,accuracy",

    "arcore_poses.csv":
        "android_camera_timestamp_ns,tx,ty,tz,"
        "qx,qy,qz,qw,tracking_state,"
        "tracking_failure_reason",

    "episodes.csv":
        "episode_id,start_timestamp_ns,end_timestamp_ns,"
        "task,object,outcome",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status,
        content={
            "code": exc.code,
            "message": exc.message,
        },
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "ingestion"
    }


def require_uuid(value: str):
    try:
        parsed = UUID(value)
    except ValueError:
        raise ApiError(
            422,
            "BUNDLE_INVALID",
            "Idempotency-Key is not a UUID",
        )

    if str(parsed) != value.lower():
        raise ApiError(
            422,
            "BUNDLE_INVALID",
            "Invalid session UUID",
        )


async def save_upload(
    upload: UploadFile,
    target: Path,
):
    digest = hashlib.sha256()
    size = 0

    await upload.seek(0)

    with target.open("wb") as output:
        while True:
            chunk = await upload.read(1024 * 1024)

            if not chunk:
                break

            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)

    return size, digest.hexdigest()


def read_header(path: Path):
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as f:
        return f.readline().rstrip("\r\n")


def parse_manifest(metadata: dict):
    entries = metadata.get("files")

    if not isinstance(entries, list):
        raise ApiError(
            422,
            "BUNDLE_INVALID",
            "metadata.files is missing",
        )

    manifest = {}

    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "Invalid manifest entry",
            )

        path = entry.get("path")

        # 현재 Android 구현은 sizeBytes를 사용함.
        # size_bytes도 향후 migration을 위해 허용.
        size = entry.get(
            "sizeBytes",
            entry.get("size_bytes"),
        )

        sha256 = entry.get("sha256")

        if (
            not isinstance(path, str)
            or not isinstance(size, int)
            or not isinstance(sha256, str)
        ):
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "Malformed manifest entry",
            )

        if path in manifest:
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                f"Duplicate manifest path: {path}",
            )

        if not SHA256_RE.fullmatch(sha256):
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                f"Invalid SHA-256: {path}",
            )

        manifest[path] = {
            "size": size,
            "sha256": sha256,
        }

    return manifest


@app.post("/sessions")
async def upload_session(request: Request):
    content_type = request.headers.get(
        "content-type",
        "",
    )

    if not content_type.lower().startswith(
        "multipart/form-data"
    ):
        raise ApiError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "multipart/form-data required",
        )

    session_id = request.headers.get(
        "Idempotency-Key"
    )

    if not session_id:
        raise ApiError(
            422,
            "BUNDLE_INVALID",
            "Idempotency-Key is required",
        )

    require_uuid(session_id)

    lock = LOCK_ROOT / session_id

    try:
        lock.mkdir()
    except FileExistsError:
        raise ApiError(
            409,
            "IDEMPOTENCY_IN_PROGRESS",
            "This session is currently uploading",
        )

    stage = None

    try:
        try:
            form = await request.form()
        except Exception as exc:
            raise ApiError(
                400,
                "MALFORMED_MULTIPART",
                str(exc),
            )

        part_lists = {}

        for name, value in form.multi_items():
            if not isinstance(value, UploadFile):
                raise ApiError(
                    400,
                    "MALFORMED_MULTIPART",
                    f"{name} must be a file part",
                )

            part_lists.setdefault(
                name,
                [],
            ).append(value)

        for name, values in part_lists.items():
            if len(values) != 1:
                raise ApiError(
                    400,
                    "MALFORMED_MULTIPART",
                    f"Duplicate part: {name}",
                )

        parts = {
            name: values[0]
            for name, values
            in part_lists.items()
        }

        metadata_upload = parts.get("metadata")

        if metadata_upload is None:
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "metadata part is missing",
            )

        if metadata_upload.filename != "metadata.json":
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "metadata filename must be metadata.json",
            )

        await metadata_upload.seek(0)

        metadata_bytes = await metadata_upload.read(
            MAX_METADATA_BYTES + 1
        )

        if len(metadata_bytes) > MAX_METADATA_BYTES:
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "metadata.json is too large",
            )

        try:
            metadata = json.loads(
                metadata_bytes.decode("utf-8")
            )
        except Exception:
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "metadata.json is invalid",
            )

        metadata_session_id = metadata.get(
            "session_id"
        )

        if metadata_session_id != session_id:
            raise ApiError(
                409,
                "IDEMPOTENCY_CONFLICT",
                "metadata session_id does not match Idempotency-Key",
            )

        streams = metadata.get(
            "camera_streams"
        )

        if not isinstance(streams, dict):
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "camera_streams is missing",
            )

        if streams.get("main") is not True:
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "main camera stream must be true",
            )

        ultrawide = streams.get("ultrawide")

        if not isinstance(ultrawide, bool):
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "ultrawide declaration is invalid",
            )

        expected_parts = dict(BASE_PARTS)

        if ultrawide:
            expected_parts.update(
                ULTRAWIDE_PARTS
            )

        if set(parts) != set(expected_parts):
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "Multipart part set does not match metadata",
            )

        for part_name, filename in expected_parts.items():
            if parts[part_name].filename != filename:
                raise ApiError(
                    422,
                    "BUNDLE_INVALID",
                    f"Invalid filename for {part_name}",
                )

        manifest = parse_manifest(metadata)

        expected_raw_files = (
            set(expected_parts.values())
            - {"metadata.json"}
        )

        if set(manifest) != expected_raw_files:
            raise ApiError(
                422,
                "BUNDLE_INVALID",
                "Manifest file set does not match bundle",
            )

        stage = Path(
            tempfile.mkdtemp(
                prefix=f"{session_id}-",
                dir=INCOMING_ROOT,
            )
        )

        (stage / "metadata.json").write_bytes(
            metadata_bytes
        )

        stats = {}

        for part_name, filename in expected_parts.items():
            if filename == "metadata.json":
                continue

            size, digest = await save_upload(
                parts[part_name],
                stage / filename,
            )

            stats[filename] = {
                "size": size,
                "sha256": digest,
            }

        for filename in expected_raw_files:
            actual = stats[filename]
            expected = manifest[filename]

            if actual["size"] <= 0:
                raise ApiError(
                    422,
                    "BUNDLE_INVALID",
                    f"{filename} is empty",
                )

            if actual["size"] != expected["size"]:
                raise ApiError(
                    422,
                    "BUNDLE_INVALID",
                    f"Size mismatch: {filename}",
                )

            if actual["sha256"] != expected["sha256"]:
                raise ApiError(
                    422,
                    "BUNDLE_INVALID",
                    f"SHA-256 mismatch: {filename}",
                )

        for filename, header in CSV_HEADERS.items():
            if read_header(stage / filename) != header:
                raise ApiError(
                    422,
                    "BUNDLE_INVALID",
                    f"Invalid CSV header: {filename}",
                )

        if ultrawide:
            filename = (
                "ultrawide_frame_timestamps.csv"
            )

            if (
                read_header(stage / filename)
                != CSV_HEADERS[
                    "main_frame_timestamps.csv"
                ]
            ):
                raise ApiError(
                    422,
                    "BUNDLE_INVALID",
                    "Invalid ultra-wide timestamp header",
                )

        final = SESSION_ROOT / session_id

        if final.exists():
            existing_metadata = (
                final / "metadata.json"
            )

            if (
                existing_metadata.is_file()
                and existing_metadata.read_bytes()
                == metadata_bytes
            ):
                shutil.rmtree(
                    stage,
                    ignore_errors=True,
                )
                stage = None

                return JSONResponse(
                    status_code=200,
                    content={
                        "session_id": session_id,
                        "result": "duplicate",
                    },
                )

            raise ApiError(
                409,
                "IDEMPOTENCY_CONFLICT",
                "session_id already exists with different metadata",
            )

        stage.rename(final)
        stage = None

        return JSONResponse(
            status_code=201,
            content={
                "session_id": session_id,
                "result": "created",
            },
        )

    finally:
        if stage is not None:
            shutil.rmtree(
                stage,
                ignore_errors=True,
            )

        try:
            lock.rmdir()
        except OSError:
            pass
