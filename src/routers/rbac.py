from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from bootstrap import get_app_container
from src.adapters.postgres_admin_store import PostgresAdminStore
from src.auth import require_auth

router = APIRouter(prefix="/admin/v1/rbac", tags=["rbac"])

class RbacRole(BaseModel):
    role_id: str
    name: str
    description: Optional[str] = None
    permissions: List[str]
    built_in: bool = False

class RbacBinding(BaseModel):
    principal_id: str
    bindings: List[Dict[str, str]] # List of {role_id, scope}

@router.get("/roles")
async def list_roles(_: Any = Depends(require_auth)) -> Dict[str, Any]:
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    roles = store.list_roles()
    return {"roles": roles}

@router.post("/roles")
async def upsert_role(role: RbacRole, _: Any = Depends(require_auth)) -> RbacRole:
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    updated = store.upsert_role(
        role.role_id, role.name, role.description or "", role.permissions, role.built_in
    )
    return RbacRole(**updated)

@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, _: Any = Depends(require_auth)) -> Dict[str, bool]:
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    success = store.delete_role(role_id)
    if not success:
        # Check if it was built-in
        roles = store.list_roles()
        for r in roles:
            if r['role_id'] == role_id and r['built_in']:
                raise HTTPException(status_code=403, detail="Cannot delete built-in roles")
        raise HTTPException(status_code=404, detail="Role not found")
    return {"success": True}

@router.get("/bindings")
async def list_bindings(_: Any = Depends(require_auth)) -> Dict[str, Any]:
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    bindings = store.list_bindings()
    return {"bindings": bindings}

@router.post("/bindings")
async def upsert_binding(binding: RbacBinding, _: Any = Depends(require_auth)) -> RbacBinding:
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    updated = store.upsert_binding(binding.principal_id, binding.bindings)
    return RbacBinding(**updated)

@router.delete("/bindings/{principal_id}")
async def delete_binding(principal_id: str, _: Any = Depends(require_auth)) -> Dict[str, bool]:
    container = get_app_container()
    store = container.resolve(PostgresAdminStore)
    success = store.delete_binding(principal_id)
    if not success:
        raise HTTPException(status_code=404, detail="Binding not found")
    return {"success": True}
