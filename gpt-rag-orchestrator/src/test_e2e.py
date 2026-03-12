"""Quick standalone test for SalesRecommendationClient.generate_recommendation()"""
import asyncio
import os
import json
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

os.environ.setdefault("APP_CONFIG_ENDPOINT", "https://appcs-2v3lfktkn4xam-gprag.azconfig.io")
os.environ.setdefault("APP_API_TOKEN", "dev-token")
os.environ.setdefault("allow_environment_variables", "true")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://rag-open-ai-test.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
os.environ.setdefault("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-52")


async def main():
    from connectors.sales_recommendation import SalesRecommendationClient

    client = SalesRecommendationClient()

    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] Starting generate_recommendation...")

    result = await client.generate_recommendation(
        customer_id="26568707",
        call_customer_id="26568707",
        model_deployment="gpt-52",
    )

    elapsed = time.time() - t0
    print(f"[{time.strftime('%H:%M:%S')}] Done in {elapsed:.1f}s")

    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(f"Result length: {len(output)} chars")
    print("--- First 2000 chars ---")
    print(output[:2000])

    # Save full result
    with open("test_e2e_result.json", "w", encoding="utf-8") as f:
        f.write(output)
    print("Full result saved to test_e2e_result.json")


if __name__ == "__main__":
    asyncio.run(main())
