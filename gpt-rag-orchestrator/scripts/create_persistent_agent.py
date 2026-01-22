#!/usr/bin/env python3
"""
Script to create a persistent Azure AI Agent and output its ID.
This agent can be reused across sessions to avoid cold-start latency.

Usage:
    python scripts/create_persistent_agent.py

Then set the AGENT_ID in App Configuration:
    az appconfig kv set --name appcs-<token> --key AGENT_ID --value <agent_id> --label gpt-rag --yes
"""

import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from azure.identity import AzureCliCredential
from azure.ai.projects import AIProjectClient


def list_existing_agents(client):
    """List all existing agents in the project."""
    print("\n📋 Existing agents in the project:")
    print("-" * 60)
    agents_found = []
    
    agents = client.agents.list_agents()
    for agent in agents:
        agents_found.append(agent)
        created = getattr(agent, 'created_at', 'N/A')
        model = getattr(agent, 'model', 'N/A')
        print(f"  Name: {agent.name}")
        print(f"  ID: {agent.id}")
        print(f"  Model: {model}")
        print(f"  Created: {created}")
        print("-" * 60)
    
    if not agents_found:
        print("  (No agents found)")
    
    return agents_found


def create_persistent_agent(client, model_name: str):
    """Create a new persistent agent."""
    print(f"\n🔨 Creating new persistent agent with model: {model_name}")
    
    # Basic system instructions - you can customize this
    instructions = """You are a helpful AI assistant that helps users find information 
and answer questions based on the knowledge base and web search.

When answering questions:
1. Search the knowledge base first for relevant information
2. Use Bing search for real-time or up-to-date information when needed
3. Provide clear, concise answers with references when available
4. Be honest when you don't have enough information to answer

Always maintain a professional and helpful tone."""

    agent = client.agents.create_agent(
        model=model_name,
        name="gpt-rag-agent-persistent",
        instructions=instructions,
    )
    
    print(f"\n✅ Agent created successfully!")
    print(f"   Name: {agent.name}")
    print(f"   ID: {agent.id}")
    
    return agent


def main():
    # Configuration - update these values
    PROJECT_ENDPOINT = os.environ.get(
        "AI_FOUNDRY_PROJECT_ENDPOINT",
        "https://aif-d5teispadppru.services.ai.azure.com/api/projects/aifoundry-default-project"
    )
    MODEL_NAME = os.environ.get("CHAT_DEPLOYMENT_NAME", "gpt5-chat")
    
    print("=" * 60)
    print("Azure AI Agent Manager")
    print("=" * 60)
    print(f"Project Endpoint: {PROJECT_ENDPOINT}")
    print(f"Model: {MODEL_NAME}")
    
    # Set longer timeout for Azure CLI
    credential = AzureCliCredential(process_timeout=60)
    
    with AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential) as client:
        # List existing agents
        existing_agents = list_existing_agents(client)
        
        # Find existing gpt-rag-agent-persistent
        persistent_agents = [a for a in existing_agents if 'persistent' in (a.name or '').lower()]
        
        if persistent_agents:
            print(f"\n📌 Found {len(persistent_agents)} persistent agent(s).")
            agent = persistent_agents[0]
            print(f"\n🔄 You can reuse this agent ID:")
            print(f"\n   AGENT_ID = {agent.id}")
        else:
            print("\n❓ No persistent agent found. Create one?")
            response = input("   Enter 'y' to create, or agent ID to use existing: ").strip()
            
            if response.lower() == 'y':
                agent = create_persistent_agent(client, MODEL_NAME)
            elif response.startswith('asst_'):
                # Use specified agent ID
                print(f"\n📌 Using specified agent: {response}")
                agent = client.agents.get_agent(response)
            else:
                print("\n❌ Aborted.")
                return
        
        # Output the command to set AGENT_ID
        print("\n" + "=" * 60)
        print("📝 To configure this agent ID in App Configuration, run:")
        print("=" * 60)
        print(f"""
az appconfig kv set --name appcs-d5teispadppru --key AGENT_ID --value "{agent.id}" --label gpt-rag --yes
""")


if __name__ == "__main__":
    main()
