"""Test GPT-5.2 with the actual full prompt to see if it responds."""
import asyncio
import os
import time

os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://rag-open-ai-test.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")


async def main():
    import httpx
    from openai import AsyncAzureOpenAI
    from azure.identity.aio import AzureCliCredential

    cred = AzureCliCredential()
    token = await cred.get_token("https://cognitiveservices.azure.com/.default")
    print(f"Token OK (len={len(token.token)})")

    client = AsyncAzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_ad_token=token.token,
        timeout=httpx.Timeout(300.0, connect=30.0),
        max_retries=0,  # No retries, fail fast
    )

    # Test 1: simple prompt (should take <5s)
    print("\n--- Test 1: Simple prompt ---")
    t0 = time.time()
    r = await client.chat.completions.create(
        model="gpt-52",
        messages=[{"role": "user", "content": "用繁體中文寫一句話介紹東森購物"}],
        max_completion_tokens=100,
    )
    print(f"  {time.time()-t0:.1f}s: {r.choices[0].message.content}")
    print(f"  Usage: {r.usage}")

    # Test 2: medium prompt (system prompt only, short user)
    system_prompt = """你是電銷話術專家。根據客戶資料產出推薦話術。
輸出JSON格式: {"summary": "客戶摘要", "opening": "開場白", "pitch": "推薦話術"}"""

    print("\n--- Test 2: Medium prompt with system ---")
    t0 = time.time()
    r = await client.chat.completions.create(
        model="gpt-52",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "客戶: 64歲女性，高雄，OB等級A，偏好保健品。請產出JSON推薦話術。"},
        ],
        max_completion_tokens=500,
    )
    print(f"  {time.time()-t0:.1f}s")
    print(f"  Usage: {r.usage}")
    print(f"  Response (first 500): {r.choices[0].message.content[:500]}")

    # Test 3: full-size prompt (real persona data)
    print("\n--- Test 3: Full prompt with real data ---")
    # Use a shorter version of persona to test
    user_content = """客戶Persona:
{"unikey3": "26568707", "性別": "女", "年齡": "64.0", "縣市": "高雄市", "OB等級": "A",
 "偏好品類": "保健品", "全通路歷史累積消費金額": "2690174", "persona": "家庭中有長壽因子，注重保養和健康"}

通話摘要: 前一通電話失敗

會員卡權益: 東森幣回饋、免運優惠、生日禮金

請產出推薦話術JSON。"""

    t0 = time.time()
    r = await client.chat.completions.create(
        model="gpt-52",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_completion_tokens=800,
    )
    print(f"  {time.time()-t0:.1f}s")
    print(f"  Usage: {r.usage}")
    print(f"  Response (first 800): {r.choices[0].message.content[:800]}")

    await cred.close()
    await client.close()
    print("\nAll tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
