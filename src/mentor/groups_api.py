from fastapi import APIRouter, status
from pydantic import BaseModel, StrictInt

from mentor import groups
from mentor.db import Database
from mentor.groups import MentorGroup
from mentor.mentors_api import Name


class GroupName(BaseModel):
    name: Name


class GroupMembers(BaseModel):
    mentor_ids: list[StrictInt]


def groups_router(database: Database) -> APIRouter:
    router = APIRouter()

    @router.get("/groups")
    async def list_groups() -> list[MentorGroup]:
        return await database.run(groups.list_groups)

    @router.post("/groups", status_code=status.HTTP_201_CREATED)
    async def create_group(body: GroupName) -> MentorGroup:
        return await database.run(lambda conn: groups.create_group(conn, body.name))

    @router.patch("/groups/{group_id}")
    async def rename_group(group_id: int, body: GroupName) -> MentorGroup:
        return await database.run(lambda conn: groups.rename_group(conn, group_id, body.name))

    @router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_group(group_id: int) -> None:
        await database.run(lambda conn: groups.delete_group(conn, group_id))

    @router.put("/groups/{group_id}/members")
    async def set_members(group_id: int, body: GroupMembers) -> MentorGroup:
        return await database.run(lambda conn: groups.set_members(conn, group_id, body.mentor_ids))

    return router
