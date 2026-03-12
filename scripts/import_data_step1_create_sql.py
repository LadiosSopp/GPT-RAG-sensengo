"""
Azure Data Import Script for 東森 Sales Agent
Imports:
1. Persona data → Azure SQL DB
2. Call logs → Azure Blob Storage → Azure AI Search (vector index)
"""
import subprocess
import json
import sys
import os

def run_az(cmd, description=""):
    """Run az CLI command and return parsed JSON output"""
    print(f"\n{'='*60}")
    print(f">> {description}")
    print(f">> az {cmd}")
    print('='*60)
    result = subprocess.run(
        f"az {cmd}",
        shell=True, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: {result.stderr.strip()}")
        return None
    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return result.stdout.strip()
    return True

def main():
    # Step 1: Verify login
    account = run_az('account show', 'Verify Azure login')
    if not account:
        print("Please run 'az login' first!")
        sys.exit(1)
    print(f"Subscription: {account.get('name', 'unknown')}")
    
    RG = "GPRAG"
    LOCATION = "eastus2"
    SQL_SERVER = "sql-2v3lfktkn4xam-gprag"
    SQL_DB = "salesagent"
    
    # Step 2: Get signed-in user info for SQL admin
    user = run_az('ad signed-in-user show', 'Get signed-in user info')
    if not user:
        print("Cannot get user info")
        sys.exit(1)
    
    user_name = user.get('userPrincipalName', user.get('displayName', ''))
    user_id = user.get('id', '')
    print(f"Admin user: {user_name} ({user_id})")
    
    # Step 3: Create SQL Server (Entra ID only auth)
    print(f"\n>>> Creating SQL Server: {SQL_SERVER}")
    result = run_az(
        f'sql server create '
        f'--name {SQL_SERVER} '
        f'--resource-group {RG} '
        f'--location {LOCATION} '
        f'--enable-ad-only-auth '
        f'--external-admin-principal-type User '
        f'--external-admin-name "{user_name}" '
        f'--external-admin-sid "{user_id}"',
        'Create SQL Server with Entra ID auth'
    )
    if result:
        print("SQL Server created successfully!")
    else:
        # Check if already exists
        existing = run_az(f'sql server show --name {SQL_SERVER} --resource-group {RG}', 'Check existing SQL Server')
        if existing:
            print("SQL Server already exists, continuing...")
        else:
            print("Failed to create SQL Server")
            sys.exit(1)
    
    # Step 4: Allow Azure services to access
    print("\n>>> Configuring firewall rule to allow Azure services...")
    run_az(
        f'sql server firewall-rule create '
        f'--server {SQL_SERVER} '
        f'--resource-group {RG} '
        f'--name AllowAzureServices '
        f'--start-ip-address 0.0.0.0 '
        f'--end-ip-address 0.0.0.0',
        'Allow Azure services access'
    )
    
    # Also allow current IP for data import
    import urllib.request
    my_ip = urllib.request.urlopen('https://api.ipify.org').read().decode('utf8')
    print(f"Current IP: {my_ip}")
    run_az(
        f'sql server firewall-rule create '
        f'--server {SQL_SERVER} '
        f'--resource-group {RG} '
        f'--name AllowMyIP '
        f'--start-ip-address {my_ip} '
        f'--end-ip-address {my_ip}',
        f'Allow current IP ({my_ip})'
    )
    
    # Step 5: Create Database (Basic tier for dev)
    print(f"\n>>> Creating database: {SQL_DB}")
    result = run_az(
        f'sql db create '
        f'--server {SQL_SERVER} '
        f'--resource-group {RG} '
        f'--name {SQL_DB} '
        f'--edition GeneralPurpose '
        f'--family Gen5 '
        f'--compute-model Serverless '
        f'--auto-pause-delay 60 '
        f'--min-capacity 0.5 '
        f'--capacity 1 '
        f'--max-size 2GB',
        'Create Serverless SQL Database'
    )
    if result:
        print(f"Database '{SQL_DB}' created!")
    else:
        existing = run_az(f'sql db show --server {SQL_SERVER} --resource-group {RG} --name {SQL_DB}', 'Check existing DB')
        if existing:
            print("Database already exists, continuing...")
        else:
            print("Failed to create database")
            sys.exit(1)
    
    print("\n" + "="*60)
    print("Phase 1: Azure SQL DB infrastructure ready!")
    print(f"  Server: {SQL_SERVER}.database.windows.net")
    print(f"  Database: {SQL_DB}")
    print(f"  Auth: Entra ID ({user_name})")
    print("="*60)

if __name__ == "__main__":
    main()
