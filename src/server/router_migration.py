from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from .room_migration import (
    RoomMigrationError,
    build_room_package,
    import_room_package,
    inspect_room_package,
)


router = APIRouter(prefix="/api")


@router.get("/exports/rooms/{room_id}/package")
async def export_room_package(request: Request, room_id: str):
    _require_room_owner_or_admin(request, room_id)
    try:
        package = build_room_package(request.app.state.db, room_id)
    except RoomMigrationError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(
        content=package,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="aikeeper-room-{room_id}.zip"'},
    )


@router.post("/imports/preview")
async def preview_room_import(request: Request, package: UploadFile = File(...)):
    _require_host_or_admin_bearer(request)
    parsed = await _read_package(package)
    return {
        "valid": True,
        "schema": parsed.manifest["schema"],
        "version": parsed.manifest["version"],
        "counts": parsed.counts,
    }


@router.post("/imports/confirm")
async def confirm_room_import(
    request: Request,
    package: UploadFile = File(...),
    confirm: str = Form("false"),
):
    account = _require_host_or_admin_bearer(request)
    if confirm.lower() != "true":
        raise HTTPException(400, "需要 confirm: true 才能导入")
    parsed = await _read_package(package)
    try:
        room_id = import_room_package(request.app.state.db, parsed, account["account_id"])
    except RoomMigrationError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"room_id": room_id, "counts": parsed.counts}


async def _read_package(package: UploadFile):
    try:
        raw = await package.read()
        return inspect_room_package(raw)
    except RoomMigrationError as exc:
        raise HTTPException(422, str(exc)) from exc


def _require_host_or_admin_bearer(request: Request) -> dict:
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        raise HTTPException(401, "需要 Bearer 认证")
    from .router_auth import get_account_from_token

    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "认证无效")
    if account.get("role") not in {"host", "admin"}:
        raise HTTPException(403, "仅 Host 或管理员可以导入")
    return account


def _require_room_owner_or_admin(request: Request, room_id: str) -> dict:
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    room = dict(room)
    if request.headers.get("X-Owner-Token", "") == room["owner_token"]:
        return room

    from .router_auth import get_account_from_token

    account = get_account_from_token(request)
    if account and (
        account.get("role") == "admin"
        or account.get("account_id") == room.get("owner_account_id")
    ):
        return room
    raise HTTPException(403, "不是房间所有者或管理员")
