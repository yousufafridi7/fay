import sys
import uuid
import json
from core.database import SessionLocal, CrewMember

def setup_agents():
    db = SessionLocal()
    owner = "champ"
    
    # 1. Clean up any existing custom (non-default assistant) crew members for owner "champ"
    existing_custom = db.query(CrewMember).filter(
        CrewMember.owner == owner,
        CrewMember.is_default_assistant == False
    ).all()
    
    for cm in existing_custom:
        print(f"Removing old agent: {cm.name} ({cm.id})")
        db.delete(cm)
    db.commit()
    
    # Define common tools list
    tools_list = [
        "web_search", "web_fetch", "read_file", 
        "create_document", "update_document", "edit_document", 
        "generate_image"
    ]
    tools_json = json.dumps(tools_list)
    
    # Define the 4 agents
    agents_data = [
        {
            "id": "fay-pm",
            "name": "Aoi (Project Manager)",
            "avatar": "anime_pm",
            "personality": (
                "You are Aoi, the Project Manager for the agent team. Your job is to communicate with the user, "
                "understand their goals, break down requirements into structured tasks, coordinate with Ren (Developer), "
                "Saya (Reviewer), and Kaito (Tester), and track progress. Always maintain a structured, clear, and professional "
                "tone, but with a friendly anime touch."
            ),
            "model": "qwen2.5:3b",
            "greeting": "Hello! I am Aoi, your Project Manager. Let's build something amazing together today! What's our main objective?"
        },
        {
            "id": "fay-dev",
            "name": "Ren (Developer)",
            "avatar": "anime_dev",
            "personality": (
                "You are Ren, the Lead Developer. You write clean, optimized, and secure code. You communicate in code snippets, "
                "architecture designs, and bug fix summaries. You work closely with Aoi (PM) to receive tasks, and Saya (Reviewer) "
                "to get your work checked. You are quiet, focused, and take pride in your craft."
            ),
            "model": "qwen2.5-coder:7b",
            "greeting": "Ren here. Ready to write some code. Pass me the specs."
        },
        {
            "id": "fay-reviewer",
            "name": "Saya (Code Reviewer)",
            "avatar": "anime_reviewer",
            "personality": (
                "You are Saya, the Code Reviewer and Architect. You double-check code written by Ren (Developer). "
                "You look for syntax errors, logical bugs, optimization opportunities, and security flaws. "
                "You give constructive feedback and either APPROVE the code for testing or REJECT it with detailed change requests."
            ),
            "model": "qwen2.5:3b",
            "greeting": "Saya here. Send me the pull request or code snippet, and I'll review it thoroughly."
        },
        {
            "id": "fay-tester",
            "name": "Kaito (QA Tester)",
            "avatar": "anime_tester",
            "personality": (
                "You are Kaito, the QA Tester. You take approved code, run local shell commands/tests, verify correctness, "
                "and ensure everything works without errors. You report detailed execution logs, shell outputs, and bug reports. "
                "You are energetic and thorough."
            ),
            "model": "qwen2.5:3b",
            "greeting": "Kaito on duty! Ready to run tests and break things to make sure they work."
        }
    ]
    
    # 2. Insert the 4 agents
    # Connects to the local Ollama instance running on port 11434
    for data in agents_data:
        agent = CrewMember(
            id=data["id"],
            owner=owner,
            name=data["name"],
            avatar=data["avatar"],
            personality=data["personality"],
            model=data["model"],
            endpoint_url="http://localhost:11434/v1",
            greeting=data["greeting"],
            enabled_tools=tools_json,
            is_active=True,
            is_default_assistant=False
        )
        db.add(agent)
        print(f"Added agent: {agent.name}")
        
    db.commit()
    print("All 4 Fay agents seeded successfully!")
    db.close()

if __name__ == "__main__":
    setup_agents()
