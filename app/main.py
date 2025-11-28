from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.responses import JSONResponse
from app.api.v1.endpoints import auth
from app.schemas.response import ApiResponse

app = FastAPI(title="FastAPI Auth Backend", version="1.0.0")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with uniform response format."""
    # If detail is already in our format, use it
    print("exec",exc.status_code)
    print("execc",exc.detail)
    if isinstance(exc.detail, dict) and "success" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail
        )
    
    # Otherwise, format it
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": str(exc.detail),
            "data": None
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with uniform response format."""
    from app.core.constants import get_status_message
    
    errors = exc.errors()
    print("errors",errors)
    # Format error details for data field
    error_details = []
    for error in errors:
        field = error["loc"][-1] if error["loc"] else "unknown"
        print("field",field)
        msg = error.get("msg", "")
        # Remove "Value error, " prefix if present
        if msg.startswith("Value error, "):
            msg = msg.replace("Value error, ", "")
        error_details.append({
            "field": field,
            "message": msg
        })
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "message": get_status_message(status.HTTP_422_UNPROCESSABLE_ENTITY),
            "data": {"validation_errors": error_details}
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all other exceptions with uniform response format."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "Internal server error",
            "data": None
        }
    )


# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])


@app.get("/")
def health_check():
    """Root health check endpoint."""
    from app.core.constants import get_status_message
    return ApiResponse(
        success=True,
        message=get_status_message(status.HTTP_200_OK),
        data={"status": "ok"}
    )
