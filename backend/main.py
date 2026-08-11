import uvicorn

if __name__ == "__main__":
    # Run the FastAPI app via uvicorn programmatically
    # using the import string "apps.api.main:app" for reload support.
    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=8000, reload=True)
