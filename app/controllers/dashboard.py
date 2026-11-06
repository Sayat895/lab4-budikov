from fastapi import APIRouter, Depends

from controllers.dependencies import get_current_user, get_database, scoped_branch_id


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(
    branch_id: int | None = None,
    user: dict = Depends(get_current_user),
    database=Depends(get_database),
):
    return database.get_dashboard_summary(scoped_branch_id(user, branch_id))
