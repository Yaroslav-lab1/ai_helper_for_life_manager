from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from backend.api.deps import CurrentUser, DbSession
from backend.models import Task
from backend.schemas.tasks import TaskCreate, TaskResponse, TaskUpdate
from backend.services.time import to_utc, utc_now

router = APIRouter(prefix="/tasks", tags=["Tasks & reminders"])


def owned_task(db: DbSession, user_id: int, task_id: int) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("", response_model=list[TaskResponse])
def list_tasks(user: CurrentUser, db: DbSession, task_status: str | None = None):
    query = select(Task).where(Task.user_id == user.id)
    if task_status:
        query = query.where(Task.status == task_status)
    return db.scalars(query.order_by(Task.status, Task.due_at, Task.created_at.desc())).all()


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, user: CurrentUser, db: DbSession):
    values = payload.model_dump()
    for key in ("due_at", "reminder_at"):
        if values.get(key) is not None:
            values[key] = to_utc(values[key], user.timezone)
    if values["status"] == "done":
        values["completed_at"] = utc_now()
    task = Task(user_id=user.id, **values)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, payload: TaskUpdate, user: CurrentUser, db: DbSession):
    task = owned_task(db, user.id, task_id)
    values = payload.model_dump(exclude_unset=True)
    for key in ("due_at", "reminder_at"):
        if key in values and values[key] is not None:
            values[key] = to_utc(values[key], user.timezone)
    if values.get("status") == "done" and task.status != "done":
        task.completed_at = utc_now()
    elif values.get("status") and values["status"] != "done":
        task.completed_at = None
    for key, value in values.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, user: CurrentUser, db: DbSession):
    db.delete(owned_task(db, user.id, task_id))
    db.commit()
    return Response(status_code=204)
