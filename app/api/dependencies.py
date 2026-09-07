from fastapi import Request
async def db(request:Request):
    with request.app.state.sessions() as session: yield session
