import asyncio
import httpx
import sys

async def test_divergence():
    print("==================================================")
    print("AURA SIMULATION REALISM DIVERGENCE TEST")
    print("==================================================")
    
    base_url = "http://localhost:8000"
    
    notion_payload = {
        "idea": "Notion AI Notes - AI-powered note taking assistant to summarize, edit, and expand pages in professional documents.",
        "industry": "SaaS",
        "market": "Knowledge workers, professionals, and students",
        "pricing": {
            "amount": 10.0,
            "currency": "USD"
        },
        "region": "Global",
        "timeline": "<3mo"
    }
    
    glass_payload = {
        "idea": "Google Glass AR Smart Glasses with heads-up display, camera, and voice controls for notifications and recording.",
        "industry": "Consumer Hardware",
        "market": "Tech enthusiasts, field workers, and consumers",
        "pricing": {
            "amount": 1500.0,
            "currency": "USD"
        },
        "region": "Global",
        "timeline": "12mo+"
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        # Run Notion AI
        print("\n[1] Running simulation for Notion AI...")
        res = await client.post(f"{base_url}/simulate", json=notion_payload)
        if res.status_code != 202:
            print(f"FAILED to trigger Notion AI simulation: {res.text}")
            sys.exit(1)
        notion_job = res.json()["job_id"]
        
        # Poll Notion AI
        print("Polling Notion AI job status...")
        notion_complete = False
        for i in range(300):
            await asyncio.sleep(2)
            status_res = await client.get(f"{base_url}/simulate/{notion_job}/status")
            status_data = status_res.json()
            if status_data["status"] == "complete":
                notion_complete = True
                break
            elif status_data["status"] == "failed":
                print(f"Notion AI simulation failed in background: {status_data}")
                sys.exit(1)
        if not notion_complete:
            print("Notion AI simulation timed out (took longer than 10 mins).")
            sys.exit(1)
        
        # Run Google Glass
        print("\n[2] Running simulation for Google Glass...")
        res = await client.post(f"{base_url}/simulate", json=glass_payload)
        if res.status_code != 202:
            print(f"FAILED to trigger Google Glass simulation: {res.text}")
            sys.exit(1)
        glass_job = res.json()["job_id"]
        
        # Poll Google Glass
        print("Polling Google Glass job status...")
        glass_complete = False
        for i in range(300):
            await asyncio.sleep(2)
            status_res = await client.get(f"{base_url}/simulate/{glass_job}/status")
            status_data = status_res.json()
            if status_data["status"] == "complete":
                glass_complete = True
                break
            elif status_data["status"] == "failed":
                print(f"Google Glass simulation failed in background: {status_data}")
                sys.exit(1)
        if not glass_complete:
            print("Google Glass simulation timed out (took longer than 10 mins).")
            sys.exit(1)
                
        # Fetch Notion AI Result
        notion_res = await client.get(f"{base_url}/simulate/{notion_job}/result")
        notion_data = notion_res.json()
        
        # Fetch Google Glass Result
        glass_res = await client.get(f"{base_url}/simulate/{glass_job}/result")
        glass_data = glass_res.json()
        
        print("\n==================================================")
        print("SIMULATION RESULTS COMPARISON")
        print("==================================================")
        
        # Notion AI Validation
        notion_adoption = notion_data["product_market_fit"]
        notion_difficulty = notion_data["launch_difficulty"]
        notion_rec = notion_data["launch_recommendation"]
        
        print("NOTION AI:")
        print(f"  - Expected Adoption: {notion_adoption}% (Target: 70-90%)")
        print(f"  - Launch Difficulty: {notion_difficulty}/100 (Target: Low)")
        print(f"  - Recommendation:    {notion_rec} (Target: Proceed)")
        
        # Google Glass Validation
        glass_adoption = glass_data["product_market_fit"]
        glass_difficulty = glass_data["launch_difficulty"]
        glass_rec = glass_data["launch_recommendation"]
        
        print("\nGOOGLE GLASS:")
        print(f"  - Expected Adoption: {glass_adoption}% (Target: 15-35%)")
        print(f"  - Launch Difficulty: {glass_difficulty}/100 (Target: High)")
        print(f"  - Recommendation:    {glass_rec} (Target: Delay or Pivot)")
        print("==================================================")
        
        # Assertions for validation
        success = True
        if not (70 <= notion_adoption <= 90):
            print("WARNING: Notion AI Adoption out of target range.")
            success = False
        if notion_difficulty >= 35:
            print("WARNING: Notion AI Launch Difficulty is not Low.")
            success = False
        if not notion_rec.startswith("Proceed"):
            print("WARNING: Notion AI Recommendation is not 'Proceed'.")
            success = False
            
        if not (15 <= glass_adoption <= 35):
            print("WARNING: Google Glass Adoption out of target range.")
            success = False
        if glass_difficulty <= 50:
            print("WARNING: Google Glass Launch Difficulty is not High.")
            success = False
        if not glass_rec.startswith("Delay or Pivot"):
            print("WARNING: Google Glass Recommendation is not 'Delay or Pivot'.")
            success = False
            
        if success:
            print("\nDIVERGENCE VALIDATION SUCCESSFUL! Predictions clearly diverged as expected.")
        else:
            print("\nWARNING: Some validation assertions failed.")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_divergence())
