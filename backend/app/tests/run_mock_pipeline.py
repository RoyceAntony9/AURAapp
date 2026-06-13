import asyncio
import httpx
import sys
import os

# Ensure backend folder is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

async def test_end_to_end():
    print("Starting integration test...")
    
    # We will test against a running server, or run the pipeline logic directly.
    # To run a clean endpoint check, we can start uvicorn in background or mock the client.
    # Let's perform live HTTP calls to the backend on localhost:8000
    base_url = "http://localhost:8000"
    
    payload = {
        "idea": "An AI-powered decentralized code reviewer that runs as a git hook and automates pull requests.",
        "industry": "SaaS",
        "market": "Software engineers and tech startups",
        "pricing": {
            "amount": 29.0,
            "currency": "USD"
        },
        "region": "Global",
        "timeline": "<3mo"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Trigger Simulation
        print(f"Triggering simulation via POST {base_url}/simulate...")
        try:
            res = await client.post(f"{base_url}/simulate", json=payload)
        except Exception as e:
            print(f"FAILED: Could not connect to API server at {base_url}. Please ensure the backend server is running.")
            print(f"Error: {e}")
            sys.exit(1)
            
        if res.status_code != 202:
            print(f"FAILED: Simulation trigger returned status code {res.status_code}. Response: {res.text}")
            sys.exit(1)
            
        data = res.json()
        job_id = data.get("job_id")
        print(f"SUCCESS: Job created. ID: {job_id}")
        
        # 2. Poll Status
        print("Polling job status...")
        complete = False
        for i in range(40):
            await asyncio.sleep(3)
            status_res = await client.get(f"{base_url}/simulate/{job_id}/status")
            status_data = status_res.json()
            progress = status_data.get("progress")
            stage = status_data.get("current_stage")
            status_str = status_data.get("status")
            print(f"[{i+1}/25] Status: {status_str} | Stage: {stage} | Progress: {progress}%")
            
            if status_str == "complete":
                complete = True
                break
            elif status_str == "failed":
                print(f"FAILED: Pipeline failed with error: {status_data.get('error')}")
                sys.exit(1)
                
        if not complete:
            print("FAILED: Job did not complete within timeout window.")
            sys.exit(1)
            
        # 3. Retrieve Results
        print("Fetching simulation results...")
        result_res = await client.get(f"{base_url}/simulate/{job_id}/result")
        if result_res.status_code != 200:
            print(f"FAILED: Result fetch returned {result_res.status_code}: {result_res.text}")
            sys.exit(1)
            
        result_data = result_res.json()
        print("SUCCESS: Result fetched successfully.")
        print(f"Opportunity Score: {result_data.get('opportunity_score')} ({result_data.get('opportunity_label')})")
        print(f"Recommendation: {result_data.get('launch_recommendation')}")
        print(f"Projections check: {len(result_data.get('revenue_projection', {}).get('projections', []))} intervals found.")
        
        # 4. Fetch Personas
        print("Fetching segment-filtered paginated personas...")
        # Get first segment name
        segments = result_data.get("market_segments", [])
        if not segments:
            print("FAILED: No market segments found in report.")
            sys.exit(1)
            
        first_segment = segments[0].get("id")
        personas_res = await client.get(f"{base_url}/simulate/{job_id}/personas?segment={first_segment}&page=1&limit=5")
        if personas_res.status_code != 200:
            print(f"FAILED: Personas fetch returned {personas_res.status_code}: {personas_res.text}")
            sys.exit(1)
            
        personas_data = personas_res.json()
        print(f"SUCCESS: Paginated personas fetched. Segment count: {personas_data.get('total_count')}")
        print(f"Sample Persona: {personas_data.get('personas')[0].get('name')} | Occupation: {personas_data.get('personas')[0].get('occupation')}")
        print("ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_end_to_end())
