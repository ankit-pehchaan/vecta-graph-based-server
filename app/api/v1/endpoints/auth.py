from fastapi import APIRouter, HTTPException, status, Depends
from app.schemas.user import UserCreateRequest, UserLoginRequest, UserData
from app.schemas.response import ApiResponse
from app.services.auth import AuthService
from app.repositories.memory import InMemoryUserRepository
from app.core.constants import get_status_message
from app.core.exceptions import UserAlreadyExistsException, InvalidCredentialsException, AppException

router = APIRouter()

# In-memory repository instance (singleton for this example)
_user_repository = InMemoryUserRepository()


async def get_auth_service() -> AuthService:
    """Dependency injection for AuthService."""
    return AuthService(user_repository=_user_repository)


@router.post("/register", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user: UserCreateRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Register a new user and return JWT tokens."""
    try:
        result = await auth_service.register_user(user.username, user.password)
        #TODOS: Set in http cookies here 
        return ApiResponse(
            success=True,
            message=get_status_message(status.HTTP_201_CREATED),
            data={
                "username": user.username,
                "access_token": result["access_token"],
                "refresh_token": result["refresh_token"],
                "token_type": "bearer"
            }
        )
    except UserAlreadyExistsException as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "success": False,
                "message": get_status_message(status.HTTP_409_CONFLICT),
                "data": e.data
            }
        )
    except AppException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "message": get_status_message(status.HTTP_400_BAD_REQUEST),
                "data": e.data
            }
        )


@router.post("/login", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def login(
    user: UserLoginRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Login user and return JWT tokens."""
    try:
        result = await auth_service.login_user(user.username, user.password)
        #TODOS: Set in http cookies here 
        return ApiResponse(
            success=True,
            message=get_status_message(status.HTTP_200_OK),
            data={
                "username": user.username,
                "access_token": result["access_token"],
                "refresh_token": result["refresh_token"],
                "token_type": "bearer"
            }
        )
    except InvalidCredentialsException as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "success": False,
                "message": get_status_message(status.HTTP_401_UNAUTHORIZED),
                "data": e.data
            }
        )
    except AppException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "message": get_status_message(status.HTTP_400_BAD_REQUEST),
                "data": e.data
            }
        )
