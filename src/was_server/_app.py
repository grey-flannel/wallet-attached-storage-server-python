"""FastAPI application implementing the Wallet Attached Storage specification."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from was_server._http_signature import ParsedSignature, verify_signature
from was_server._storage_factory import create_storage
from was_server._urn_uuid import make_urn_uuid

app = FastAPI()
storage = create_storage()


def _problem_response(status: int, title: str, detail: str, pointer: str = "/authorization") -> JSONResponse:
    """Return an ``application/problem+json`` error response."""
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://wallet.storage/spec#{title.lower().replace(' ', '-')}",
            "title": title,
            "errors": [{"detail": detail, "pointer": pointer}],
        },
        media_type="application/problem+json",
    )


def _verify_request(request: Request) -> ParsedSignature | JSONResponse:
    """Verify the HTTP Signature on a request.

    Returns the parsed signature on success, or an error JSONResponse on failure.
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        return _problem_response(401, "Unauthorized", "Missing Authorization header")
    try:
        return verify_signature(authorization, request.method, request.url.path)
    except ValueError as exc:
        return _problem_response(401, "Unauthorized", str(exc))


def _check_controller(parsed: ParsedSignature, controller: str) -> JSONResponse | None:
    """Check that the signer's DID matches the space controller. Returns error response or None."""
    if parsed.controller != controller:
        return _problem_response(403, "Forbidden", "Signer does not match space controller")
    return None


# ---------------------------------------------------------------------------
# Space routes
# ---------------------------------------------------------------------------


@app.put("/space/{space_id}")
async def put_space(space_id: str, request: Request) -> Response:
    """Create or update a space."""
    result = _verify_request(request)
    if isinstance(result, JSONResponse):
        return result
    parsed = result

    body = await request.json()
    controller = body.get("controller")
    space_urn = body.get("id")

    if not controller or not space_urn:
        return _problem_response(400, "Bad Request", "Body must include 'id' and 'controller'", pointer="/body")

    err = _check_controller(parsed, controller)
    if err:
        return err

    storage.put_space(space_id, space_urn, controller)
    return Response(status_code=204)


@app.get("/space/{space_id}")
async def get_space(space_id: str, request: Request) -> Response:
    """Get space metadata."""
    result = _verify_request(request)
    if isinstance(result, JSONResponse):
        return result

    space = storage.get_space(space_id)
    if space is None:
        return _problem_response(404, "Not Found", f"Space {space_id!r} not found", pointer="/space")

    # Check controller
    err = _check_controller(result, space.controller)
    if err:
        return err

    return JSONResponse(content={"id": space.id, "controller": space.controller})


@app.delete("/space/{space_id}")
async def delete_space(space_id: str, request: Request) -> Response:
    """Delete a space and all its contents."""
    result = _verify_request(request)
    if isinstance(result, JSONResponse):
        return result

    space = storage.get_space(space_id)
    if space is not None:
        err = _check_controller(result, space.controller)
        if err:
            return err

    storage.delete_space(space_id)
    return Response(status_code=204)


@app.post("/spaces/")
async def create_space(request: Request) -> Response:
    """Create a new space with a server-generated ID."""
    result = _verify_request(request)
    if isinstance(result, JSONResponse):
        return result

    new_uuid = uuid.uuid4()
    space_urn = make_urn_uuid(new_uuid)
    storage.put_space(str(new_uuid), space_urn, result.controller)

    return Response(
        status_code=201,
        headers={"location": f"/space/{new_uuid}"},
    )


@app.get("/spaces/")
async def list_spaces(request: Request) -> Response:
    """List spaces the authenticated user controls."""
    result = _verify_request(request)
    if isinstance(result, JSONResponse):
        return result

    spaces = storage.list_spaces(result.controller)
    items = [{"id": s.id, "controller": s.controller} for s in spaces]
    return JSONResponse(content=items)


# ---------------------------------------------------------------------------
# Resource routes
# ---------------------------------------------------------------------------


@app.get("/space/{space_id}/{path:path}")
async def get_resource(space_id: str, path: str, request: Request) -> Response:
    """Get a resource — unsigned reads allowed."""
    resource_path = f"/{path}"
    resource = storage.get_resource(space_id, resource_path)
    if resource is None:
        return _problem_response(404, "Not Found", f"Resource {resource_path!r} not found", pointer="/resource")
    return Response(content=resource.content, media_type=resource.content_type)


@app.put("/space/{space_id}/{path:path}")
async def put_resource(space_id: str, path: str, request: Request) -> Response:
    """Create or update a resource."""
    result = _verify_request(request)
    if isinstance(result, JSONResponse):
        return result

    space = storage.get_space(space_id)
    if space is None:
        return _problem_response(404, "Not Found", f"Space {space_id!r} not found", pointer="/space")

    err = _check_controller(result, space.controller)
    if err:
        return err

    body = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    resource_path = f"/{path}"
    storage.put_resource(space_id, resource_path, body, content_type)
    return Response(status_code=204)


@app.post("/space/{space_id}/{path:path}")
async def post_resource(space_id: str, path: str, request: Request) -> Response:
    """Create a resource (returns 201)."""
    result = _verify_request(request)
    if isinstance(result, JSONResponse):
        return result

    space = storage.get_space(space_id)
    if space is None:
        return _problem_response(404, "Not Found", f"Space {space_id!r} not found", pointer="/space")

    err = _check_controller(result, space.controller)
    if err:
        return err

    body = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    resource_path = f"/{path}"
    storage.put_resource(space_id, resource_path, body, content_type)
    return Response(status_code=201)


@app.delete("/space/{space_id}/{path:path}")
async def delete_resource(space_id: str, path: str, request: Request) -> Response:
    """Delete a resource (idempotent)."""
    result = _verify_request(request)
    if isinstance(result, JSONResponse):
        return result

    space = storage.get_space(space_id)
    if space is not None:
        err = _check_controller(result, space.controller)
        if err:
            return err

    resource_path = f"/{path}"
    storage.delete_resource(space_id, resource_path)
    return Response(status_code=204)
