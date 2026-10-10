from fastapi import APIRouter, status
from pydantic import BaseModel, StrictInt

from seek import groups
from seek.db import Database
from seek.channels_api import Name
from seek.groups import Group


class GroupName(BaseModel):
    name: Name


class GroupMembers(BaseModel):
    channel_ids: list[StrictInt]


def groups_router(database: Database) -> APIRouter:
    router = APIRouter()

    @router.get("/groups")
    async def list_groups() -> list[Group]:
        return await database.run(groups.list_groups)

    @router.post("/groups", status_code=status.HTTP_201_CREATED)
    async def create_group(body: GroupName) -> Group:
        return await database.run(lambda conn: groups.create_group(conn, body.name))

    @router.patch("/groups/{group_id}")
    async def rename_group(group_id: int, body: GroupName) -> Group:
        return await database.run(lambda conn: groups.rename_group(conn, group_id, body.name))

    @router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_group(group_id: int) -> None:
        await database.run(lambda conn: groups.delete_group(conn, group_id))

    @router.put("/groups/{group_id}/members")
    async def set_members(group_id: int, body: GroupMembers) -> Group:
        return await database.run(lambda conn: groups.set_members(conn, group_id, body.channel_ids))

    return router
