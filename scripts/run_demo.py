"""
SENTINEL-X — Interactive Demo Script.

Sends a 'late interrupt' scenario to the live FastAPI server.
Must be run while `uvicorn sentinel_x.main:app` is running.
"""

import asyncio
import httpx


async def main():
    print("--- SENTINEL-X Interactive Demo ---")
    
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        # 1. Create Session
        print("\n1. Creating session...")
        res = await client.post("/sessions", json={"goal": "Plan Chennai to Delhi trip"})
        if res.status_code != 200:
            print("Failed to connect to API. Is FastAPI running on port 8000?")
            return
        
        session_id = res.json()["session_id"]
        print(f"   -> Session created: {session_id}")
        
        # 2. Start Execution
        print("\n2. Starting execution loop...")
        await client.post(f"/sessions/{session_id}/start")
        
        # Wait a bit so it reaches the 'book' phase
        print("   -> Letting it run for 1 second...")
        await asyncio.sleep(1.0)
        
        # 3. Inject semantic interrupt
        print("\n3. Injecting Late Interrupt: 'Stop the booking.'")
        res = await client.post(f"/sessions/{session_id}/interrupt", json={
            "raw_text": "Stop the booking."
        })
        
        data = res.json()
        print(f"   -> Intervention Chosen: {data['decision']}")
        print(f"   -> Preempted Tasks: {data['preempted']}")
        print(f"   -> Preserved Tasks: {data['preserved']}")
        
        print("\nDemo completed successfully. View the React Control Room for visual state.")

if __name__ == "__main__":
    asyncio.run(main())
