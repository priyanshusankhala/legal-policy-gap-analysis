"""
Single command to launch the Coback Compliance AI Interactive Workspace.
"""
import uvicorn

if __name__ == "__main__":
    print("\nStarting Coback Compliance AI Workspace...")
    print("Open http://localhost:8000 in your browser to interact with the system.\n")
    uvicorn.run("src.app:app", host="0.0.0.0", port=8000, reload=True)